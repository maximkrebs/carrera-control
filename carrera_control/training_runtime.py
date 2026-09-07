"""Runtime loop connecting camera observations, profile learning, and the CU."""

from __future__ import annotations

import csv
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import cv2

from .cu_controller import CarreraCuController
from .stage_control import ramped_stage
from .track_graph import TrackGraph, load_track_graph
from .training import SegmentProfile, TrainingConfig, create_initial_profile, load_profile, save_profile, segment_for_position
from .vision import DetectionConfig, find_vehicle


@dataclass(frozen=True)
class RuntimeConfig:
    """Safety and stopping parameters for one training run."""

    duration_s: float = 1800.0
    lost_timeout_s: float = 0.5
    max_track_distance_px: float = 55.0
    stall_window_s: float = 1.2
    stall_distance_px: float = 25.0
    min_lap_s: float = 2.5
    save_interval_s: float = 5.0
    slow_start_s: float = 4.0
    start_stage: int = 5
    camera_index: int = 1
    frame_width: int = 1280
    frame_height: int = 720

    def __post_init__(self) -> None:
        if self.duration_s <= 0 or self.lost_timeout_s <= 0 or self.save_interval_s <= 0:
            raise ValueError("duration_s, lost_timeout_s, and save_interval_s must be positive.")
        if self.max_track_distance_px <= 0 or self.stall_window_s <= 0 or self.stall_distance_px <= 0:
            raise ValueError("track and stall thresholds must be positive.")
        if self.min_lap_s <= 0 or self.slow_start_s < 0:
            raise ValueError("min_lap_s must be positive and slow_start_s must not be negative.")


@dataclass
class TrainingRunState:
    """Mutable runtime state kept separate from the learned profile."""

    previous_node: int | None = None
    progress_nodes: int = 0
    lap_started_at: float | None = None
    valid_lap: bool = True
    lap_count: int = 0
    best_lap_s: float | None = None
    last_lap_s: float | None = None
    last_segment: int = 0
    lost_since: float | None = None
    incident_active: bool = False
    reacquired_at: float | None = None
    motion: deque[tuple[float, float, float]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.motion is None:
            self.motion = deque()


def run_training(
    track_graph_path: str | Path,
    output_root: str | Path,
    profile_path: str | Path | None = None,
    training_config: TrainingConfig | None = None,
    runtime_config: RuntimeConfig | None = None,
    detection_config: DetectionConfig | None = None,
    port: str = "COM4",
    baudrate: int = 115200,
    show_gui: bool = True,
    learn: bool = True,
    web_port: int | None = None,
) -> Path:
    """Run camera-guided online training for a bounded amount of time.

    A clean lap calls :meth:`SegmentProfile.record_clean_lap`. A lost,
    off-track, or stalled vehicle calls :meth:`SegmentProfile.record_crash_at_node`.
    The profile and lap history are saved after every lap and at the configured
    periodic interval. The returned directory contains the complete run state.
    """
    graph = load_track_graph(track_graph_path)
    active_training = training_config or TrainingConfig()
    active_runtime = runtime_config or RuntimeConfig()
    profile = load_profile(profile_path) if profile_path is not None else create_initial_profile(graph, active_training)
    if profile.config.segment_count != active_training.segment_count:
        raise ValueError("Training profile and training configuration use different segment counts.")

    run_dir = Path(output_root) / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=False)
    initial_stages = list(profile.stages)
    profile_output = run_dir / "profile.json"
    snapshot_dir = run_dir / "profile_snapshots"
    snapshot_dir.mkdir()
    lap_output = run_dir / "lap_times.csv"
    event_output = run_dir / "events.jsonl"
    save_profile(profile, profile_output)
    _write_lap_header(lap_output)

    capture = cv2.VideoCapture(active_runtime.camera_index, cv2.CAP_DSHOW)
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, active_runtime.frame_width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, active_runtime.frame_height)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"Camera {active_runtime.camera_index} could not be opened.")

    state = TrainingRunState()
    problem_spots: dict[int, dict[str, float | int | str]] = {}
    web_state = None
    web_server = None
    if web_port is not None:
        from .web_ui import WebState, start_web_ui

        web_state = WebState()
        web_state.update(
            track_nodes=[(node.x, node.y) for node in graph.nodes],
            problem_spots=[],
            segment_centers=_segment_centers(graph, profile.segment_count),
        )
        web_server = start_web_ui(web_state, web_port)
        print(f"WebUI: http://127.0.0.1:{web_port}/")
    controller = CarreraCuController(port=port, baudrate=baudrate)
    started_at = time.monotonic()
    last_save_at = started_at
    last_command_at = started_at
    current_stage = 0
    previous_center: tuple[int, int] | None = None
    try:
        controller.open()
        controller.set_stage(0)
        while time.monotonic() - started_at < active_runtime.duration_s:
            received, frame = capture.read()
            now = time.monotonic()
            elapsed = now - started_at
            if not received:
                _record_event(event_output, elapsed, "camera_error", state.last_segment)
                break

            detection = find_vehicle(frame, detection_config, previous_center)
            target_stage = 0
            if detection is None:
                target_stage = 0
                if state.lost_since is None:
                    state.lost_since = now
                if now - state.lost_since >= active_runtime.lost_timeout_s:
                    _record_incident(profile, state, event_output, elapsed, "vehicle_lost", state.previous_node, graph.node_count, learn, problem_spots, graph)
            else:
                previous_center = detection.center
                state.lost_since = None
                node_index, distance_px = _nearest_node_and_distance(detection.center, graph)
                segment = segment_for_position(detection.center, graph, profile.segment_count)
                state.last_segment = segment
                state.motion.append((now, float(detection.center[0]), float(detection.center[1])))
                while state.motion and now - state.motion[0][0] > active_runtime.stall_window_s:
                    state.motion.popleft()

                off_track = distance_px > active_runtime.max_track_distance_px
                stalled = _is_stalled(state.motion, active_runtime.stall_window_s, active_runtime.stall_distance_px)
                if off_track or stalled:
                    target_stage = 0
                    reason = "off_track" if off_track else "stalled"
                    _record_incident(profile, state, event_output, elapsed, reason, node_index, graph.node_count, learn, problem_spots, graph)
                else:
                    state.incident_active = False
                    if state.reacquired_at is None:
                        state.reacquired_at = now
                    target_stage = profile.command_stage(segment)
                    target_stage = ramped_stage(target_stage, now - state.reacquired_at, active_runtime.slow_start_s, active_runtime.start_stage)
                    _update_lap_progress(profile, state, event_output, lap_output, snapshot_dir, now, elapsed, node_index, graph.node_count, active_runtime, learn)

            if target_stage != current_stage or now - last_command_at >= 0.2:
                controller.set_stage_fast(target_stage)
                current_stage = target_stage
                last_command_at = now

            if now - last_save_at >= active_runtime.save_interval_s:
                save_profile(profile, profile_output)
                _write_runtime_state(run_dir, state, elapsed)
                last_save_at = now

            if show_gui:
                _show_training_frame(frame, detection, target_stage, state)
                if cv2.waitKey(1) & 0xFF in {ord("q"), 27}:
                    break
            if web_state is not None:
                web_state.update(
                    elapsed_s=elapsed,
                    stage=target_stage,
                    lap_count=state.lap_count,
                    current_lap_s=None if state.lap_started_at is None else now - state.lap_started_at,
                    last_lap_s=state.last_lap_s,
                    best_lap_s=state.best_lap_s,
                    segment=state.last_segment,
                    profile_stages=[round(value, 3) for value in profile.stages],
                    profile_changes=[round(value - initial_stages[index], 3) for index, value in enumerate(profile.stages)],
                    profile_clean_laps=profile.clean_laps,
                    profile_crashes=profile.crashes,
                    learn=learn,
                    incident_active=state.incident_active,
                    problem_spots=list(problem_spots.values()),
                    danger_segments=[
                        {"segment": index, "count": count, "x": center[0], "y": center[1]}
                        for index, (count, center) in enumerate(zip(profile.crashes, _segment_centers(graph, profile.segment_count)))
                        if count > 0
                    ],
                )
                web_state.update_frame(frame)
    finally:
        controller.stop()
        controller.close()
        capture.release()
        cv2.destroyAllWindows()
        if web_server is not None:
            web_server.shutdown()
        save_profile(profile, profile_output)
        _write_runtime_state(run_dir, state, time.monotonic() - started_at)
    return run_dir


def _update_lap_progress(
    profile: SegmentProfile,
    state: TrainingRunState,
    event_path: Path,
    lap_path: Path,
    snapshot_dir: Path,
    now: float,
    elapsed: float,
    node_index: int,
    node_count: int,
    runtime: RuntimeConfig,
    learn: bool,
) -> None:
    if state.lap_started_at is None:
        state.lap_started_at = now
        state.previous_node = node_index
        return
    delta = forward_node_delta(state.previous_node, node_index, node_count)
    state.progress_nodes += delta
    state.previous_node = node_index
    if state.progress_nodes < node_count:
        return
    lap_time = now - state.lap_started_at
    state.progress_nodes %= node_count
    state.lap_started_at = now
    state.last_lap_s = lap_time
    if lap_time < runtime.min_lap_s or not state.valid_lap:
        state.valid_lap = True
        _record_event(event_path, elapsed, "lap_invalid", state.last_segment, lap_time)
        return
    selected = profile.record_clean_lap() if learn else None
    state.lap_count += 1
    state.best_lap_s = lap_time if state.best_lap_s is None else min(state.best_lap_s, lap_time)
    with lap_path.open("a", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow((state.lap_count, lap_time, state.best_lap_s, selected))
    if learn:
        save_profile(profile, snapshot_dir / f"lap-{state.lap_count:04d}.json")
    _record_event(event_path, elapsed, "clean_lap", state.last_segment, lap_time, selected)


def forward_node_delta(previous: int | None, current: int, node_count: int) -> int:
    """Return plausible forward progress, rejecting implausible camera jumps."""
    if previous is None:
        return 0
    delta = (current - previous) % node_count
    return delta if delta <= node_count // 4 else 0


def _record_incident(
    profile: SegmentProfile,
    state: TrainingRunState,
    event_path: Path,
    elapsed: float,
    reason: str,
    node_index: int | None = None,
    node_count: int | None = None,
    learn: bool = True,
    problem_spots: dict[int, dict[str, float | int | str]] | None = None,
    graph: TrackGraph | None = None,
) -> None:
    if state.incident_active:
        return
    state.valid_lap = False
    state.reacquired_at = None
    state.progress_nodes = 0
    state.previous_node = None
    state.incident_active = True
    cause = profile.record_crash_at_node(node_index, node_count) if learn and node_index is not None and node_count is not None else None
    if problem_spots is not None and node_index is not None and graph is not None:
        node = graph.nodes[node_index]
        spot = problem_spots.setdefault(node_index, {"node_index": node_index, "x": node.x, "y": node.y, "count": 0, "last_reason": reason})
        spot["count"] = int(spot["count"]) + 1
        spot["last_reason"] = reason
        if cause is not None:
            spot["cause_segment"] = cause
    _record_event(event_path, elapsed, reason, state.last_segment, cause_segment=cause)


def _nearest_node_and_distance(position: tuple[int, int], graph: TrackGraph) -> tuple[int, float]:
    distances = [((node.x - position[0]) ** 2 + (node.y - position[1]) ** 2) ** 0.5 for node in graph.nodes]
    index = min(range(graph.node_count), key=distances.__getitem__)
    return index, distances[index]


def _segment_centers(graph: TrackGraph, segment_count: int) -> list[tuple[float, float]]:
    """Return visual center points for profile segments on the cyclic graph."""
    centers: list[tuple[float, float]] = []
    for segment in range(segment_count):
        start = segment * graph.node_count // segment_count
        end = (segment + 1) * graph.node_count // segment_count
        nodes = graph.nodes[start:max(start + 1, end)]
        centers.append((sum(node.x for node in nodes) / len(nodes), sum(node.y for node in nodes) / len(nodes)))
    return centers


def _is_stalled(motion: deque[tuple[float, float, float]], window_s: float, distance_px: float) -> bool:
    if len(motion) < 2 or motion[-1][0] - motion[0][0] < window_s:
        return False
    x_values = [sample[1] for sample in motion]
    y_values = [sample[2] for sample in motion]
    span = ((max(x_values) - min(x_values)) ** 2 + (max(y_values) - min(y_values)) ** 2) ** 0.5
    return span <= distance_px


def _write_lap_header(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(("lap", "lap_time_s", "best_lap_s", "updated_segment"))


def _record_event(path: Path, elapsed: float, event: str, segment: int, lap_time: float | None = None, updated_segment: int | None = None, cause_segment: int | None = None) -> None:
    payload = {"elapsed_s": round(elapsed, 3), "event": event, "segment": segment}
    if lap_time is not None:
        payload["lap_time_s"] = round(lap_time, 4)
    if updated_segment is not None:
        payload["updated_segment"] = updated_segment
    if cause_segment is not None:
        payload["cause_segment"] = cause_segment
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def _write_runtime_state(run_dir: Path, state: TrainingRunState, elapsed: float) -> None:
    payload = {"elapsed_s": elapsed, "lap_count": state.lap_count, "last_lap_s": state.last_lap_s, "best_lap_s": state.best_lap_s, "last_segment": state.last_segment}
    (run_dir / "runtime_state.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _show_training_frame(frame, detection, stage: int, state: TrainingRunState) -> None:
    if detection is not None:
        x, y, width, height = detection.rect
        cv2.rectangle(frame, (x, y), (x + width, y + height), (0, 255, 255), 2)
    cv2.putText(frame, f"stage={stage} lap={state.lap_count} segment={state.last_segment}", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.imshow("Carrera Training", frame)


def find_best_clean_profile(training_root: str | Path) -> Path:
    """Return the snapshot belonging to the fastest recorded clean lap."""
    root = Path(training_root)
    candidates: list[tuple[float, Path]] = []
    for run_dir in root.glob("*"):
        lap_file = run_dir / "lap_times.csv"
        snapshot_dir = run_dir / "profile_snapshots"
        if not lap_file.exists() or not snapshot_dir.exists():
            continue
        with lap_file.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                snapshot = snapshot_dir / f"lap-{int(row['lap']):04d}.json"
                if snapshot.exists():
                    candidates.append((float(row["lap_time_s"]), snapshot))
    if not candidates:
        raise FileNotFoundError(f"No clean-lap profile snapshots found below {root}.")
    return min(candidates, key=lambda item: item[0])[1]