"""Record one camera-tracked lap for later track and training work.

This module deliberately only records the driven path. It does not optimize
gas, modify a profile, or make training decisions. The vehicle is driven at a
fixed CU stage while its detected center is written in time order.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import cv2

from .cu_controller import CarreraCuController
from .track_graph import build_track_graph, save_track_graph
from .vision import Detection, DetectionConfig, find_vehicle


@dataclass
class LapProgress:
    """State used to distinguish a full lap from sitting at the start point."""

    moved_away: bool = False
    path: list[tuple[float, float, float, float]] = field(default_factory=list)


def lost_timeout_expired(lost_since: float | None, now: float, timeout_s: float) -> bool:
    """Return whether a missing vehicle detection exceeded the safety timeout."""
    return lost_since is not None and now - lost_since >= timeout_s


def lap_completed(
    progress: LapProgress,
    current: tuple[float, float],
    start: tuple[float, float],
    away_threshold_px: float = 80.0,
    return_threshold_px: float = 40.0,
) -> bool:
    """Return whether the car left the start and has now returned to it."""
    distance = ((current[0] - start[0]) ** 2 + (current[1] - start[1]) ** 2) ** 0.5
    if not progress.moved_away:
        if distance >= away_threshold_px:
            progress.moved_away = True
        return False
    return distance <= return_threshold_px


def record_calibration_lap(
    output_root: str | Path,
    stage: int = 5,
    timeout_s: float = 120.0,
    camera_index: int = 1,
    frame_width: int = 1280,
    frame_height: int = 720,
    detection_config: DetectionConfig | None = None,
    port: str = "COM4",
    baudrate: int = 115200,
    show_gui: bool = True,
    lost_timeout_s: float = 0.5,
    away_threshold_px: float = 80.0,
    return_threshold_px: float = 40.0,
    node_spacing_px: float = 8.0,
    smoothing_window: int = 5,
) -> Path:
    """Drive one fixed-stage lap and save its timestamped detection path.

    The returned directory contains ``path.csv`` and ``metadata.json``. Press
    ``q`` or ``Esc`` in the preview window to stop early. On every exit path,
    the CU controller sends stage zero and closes the serial connection.
    """
    if timeout_s <= 0:
        raise ValueError("timeout_s must be greater than zero.")
    if lost_timeout_s <= 0:
        raise ValueError("lost_timeout_s must be greater than zero.")
    if not 0 <= away_threshold_px or not 0 <= return_threshold_px:
        raise ValueError("Lap distance thresholds must not be negative.")

    run_dir = Path(output_root) / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=False)
    progress = LapProgress()
    start_position: tuple[float, float] | None = None
    previous_center: tuple[int, int] | None = None
    completed = False
    stop_reason = "timeout"
    lost_since: float | None = None
    started_at = time.monotonic()

    capture = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, frame_width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_height)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"Camera {camera_index} could not be opened.")

    controller = CarreraCuController(port=port, baudrate=baudrate)
    try:
        controller.open()
        controller.set_stage(stage)
        while time.monotonic() - started_at < timeout_s:
            received, frame = capture.read()
            now = time.monotonic()
            if not received:
                raise RuntimeError("Camera frame could not be read.")

            detection = find_vehicle(frame, detection_config, previous_center)
            if detection is not None:
                lost_since = None
                previous_center = detection.center
                if start_position is None:
                    start_position = detection.center
                progress.path.append(_path_row(now - started_at, detection))
                if lap_completed(progress, detection.center, start_position, away_threshold_px, return_threshold_px):
                    completed = True
                    stop_reason = "lap_completed"
                    break
                controller.set_stage_fast(stage)
            else:
                if lost_since is None:
                    lost_since = now
                if lost_timeout_expired(lost_since, now, lost_timeout_s):
                    controller.stop()
                    stop_reason = "vehicle_lost_off_track"
                    break

            if show_gui:
                _show_preview(frame, detection, progress, start_position)
                if cv2.waitKey(1) & 0xFF in {ord("q"), 27}:
                    break
    finally:
        controller.stop()
        controller.close()
        capture.release()
        cv2.destroyAllWindows()

    _write_run(run_dir, progress.path, completed, stage, camera_index, node_spacing_px, smoothing_window, stop_reason)
    return run_dir


def _path_row(elapsed_s: float, detection: Detection) -> tuple[float, float, float, float]:
    return (elapsed_s, float(detection.center[0]), float(detection.center[1]), detection.area)


def _show_preview(
    frame,
    detection: Detection | None,
    progress: LapProgress,
    start_position: tuple[float, float] | None,
) -> None:
    if detection is not None:
        x, y, width, height = detection.rect
        cv2.rectangle(frame, (x, y), (x + width, y + height), (0, 255, 255), 2)
    if start_position is not None:
        cv2.circle(frame, (round(start_position[0]), round(start_position[1])), 12, (255, 0, 255), 2)
    status = "moved away" if progress.moved_away else "waiting for departure"
    cv2.putText(frame, f"recognition lap: {status} points={len(progress.path)}", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.imshow("Carrera Recognition Lap", frame)


def _write_run(
    run_dir: Path,
    path: list[tuple[float, float, float, float]],
    completed: bool,
    stage: int,
    camera_index: int,
    node_spacing_px: float,
    smoothing_window: int,
    stop_reason: str,
) -> None:
    with (run_dir / "path.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("elapsed_s", "x", "y", "area"))
        writer.writerows(path)
    metadata = {
        "completed": completed,
        "stage": stage,
        "camera_index": camera_index,
        "point_count": len(path),
        "stop_reason": stop_reason,
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    if completed:
        graph = build_track_graph(path, node_spacing_px, smoothing_window)
        save_track_graph(graph, run_dir / "track_graph.json")