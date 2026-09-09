"""Conservative online training of a CU stage profile along a track graph.

The module contains no camera or serial code. It is the decision core that a
future autonomous-drive loop can call after each observation and completed lap.
The profile starts below the CU's maximum, explores exits after corners first,
and decreases each segment's learning step as that segment is changed more
often, similar to an AdaGrad update.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from math import sqrt
from pathlib import Path

from .stage_control import clamp_stage
from .track_graph import TrackGraph


@dataclass
class TrainingConfig:
    """Bounds and update sizes for the online profile learner."""

    segment_count: int = 24
    initial_stage: int = 7
    minimum_stage: int = 5
    maximum_stage: int = 15
    curvature_stage_reduction: float = 0.4
    base_learning_rate: float = 1.0
    crash_penalty: float = 1.5
    corner_threshold_percentile: float = 0.75
    corner_exit_segments: int = 2
    crash_search_window_segments: int = 2
    crash_search_expansion_segments: int = 2
    crash_peak_margin: float = 0.5
    crash_cooldown_laps: int = 3

    def __post_init__(self) -> None:
        if self.segment_count < 3:
            raise ValueError("segment_count must be at least 3.")
        if not 0 <= self.minimum_stage <= self.initial_stage <= self.maximum_stage <= 15:
            raise ValueError("stage bounds must satisfy 0 <= minimum <= initial <= maximum <= 15.")
        if self.curvature_stage_reduction < 0 or self.base_learning_rate <= 0 or self.crash_penalty <= 0:
            raise ValueError("learning and curvature values must be positive or zero as appropriate.")
        if not 0.5 <= self.corner_threshold_percentile <= 1.0:
            raise ValueError("corner_threshold_percentile must be between 0.5 and 1.0.")
        if self.corner_exit_segments < 1:
            raise ValueError("corner_exit_segments must be positive.")
        if self.crash_search_window_segments < 1 or self.crash_search_expansion_segments < 1:
            raise ValueError("crash search window values must be positive.")
        if self.crash_peak_margin < 0:
            raise ValueError("crash_peak_margin must not be negative.")
        if self.crash_cooldown_laps < 0:
            raise ValueError("crash_cooldown_laps must not be negative.")


@dataclass
class SegmentProfile:
    """Current stage targets and per-segment learning statistics."""

    stages: list[float]
    accumulated_squared_updates: list[float]
    clean_laps: list[int]
    crashes: list[int]
    incident_sites: list[int]
    preferred_segments: list[int]
    config: TrainingConfig
    cooldown_laps: list[int] = field(default_factory=list)
    lap_count: int = 0

    def __post_init__(self) -> None:
        if not self.cooldown_laps:
            self.cooldown_laps = [0] * self.segment_count

    @property
    def segment_count(self) -> int:
        """Return the number of profile segments."""
        return len(self.stages)

    def command_stage(self, segment: int) -> int:
        """Return the integer CU stage to send for a segment."""
        self._check_segment(segment)
        return clamp_stage(self.stages[segment])

    def learning_rate(self, segment: int) -> float:
        """Return the current AdaGrad-like learning rate for a segment."""
        self._check_segment(segment)
        return self.config.base_learning_rate / sqrt(1.0 + self.accumulated_squared_updates[segment])

    def record_clean_lap(self) -> int | None:
        """Reward one preferred unexplored segment and return its index.

        A clean lap changes one segment only. Corner exit segments are only
        prioritized until each has received its first update once, so that
        other segments are not starved of updates forever afterwards. Segments
        still cooling down after a crash are excluded so a reduction isn't
        immediately undone on the very next clean lap.
        """
        self.lap_count += 1
        self._tick_cooldowns()
        candidates = [
            index
            for index in self.preferred_segments
            if self.stages[index] < self.config.maximum_stage
            and self.clean_laps[index] == 0
            and self.cooldown_laps[index] == 0
        ]
        if not candidates:
            candidates = [
                index
                for index, stage in enumerate(self.stages)
                if stage < self.config.maximum_stage and self.cooldown_laps[index] == 0
            ]
        if not candidates:
            return None
        selected = min(candidates, key=lambda index: (self.stages[index], self.accumulated_squared_updates[index], index))
        self._apply_update(selected, self.learning_rate(selected))
        self.clean_laps[selected] += 1
        return selected

    def record_crash(self, segment: int) -> int:
        """Mark an accident and reduce the preceding high-speed cause segment.

        ``segment`` is the observed incident site. The actual reduction is
        normally applied to an earlier segment with a clearly higher stage,
        because the car often leaves the track after carrying too much speed
        out of the preceding section. Repeated incidents expand the backward
        search window for that site.
        """
        self._check_segment(segment)
        self._tick_cooldowns()
        self.incident_sites[segment] += 1
        cause_segment = self._find_crash_cause(segment)
        self._reduce_segment(cause_segment)
        return cause_segment

    def record_crash_at_node(self, node_index: int, node_count: int) -> int:
        """Mark a graph-node incident and return the reduced cause segment."""
        segment = segment_for_node(node_index, node_count, self.segment_count)
        return self.record_crash(segment)

    def _find_crash_cause(self, incident_segment: int) -> int:
        incident_count = self.incident_sites[incident_segment]
        window = self.config.crash_search_window_segments + (
            incident_count - 1
        ) * self.config.crash_search_expansion_segments
        previous_segments = [
            (incident_segment - distance) % self.segment_count
            for distance in range(1, min(window, self.segment_count - 1) + 1)
        ]
        if not previous_segments:
            return incident_segment
        peak_segment = max(previous_segments, key=lambda index: self.stages[index])
        if self.stages[peak_segment] >= self.stages[incident_segment] + self.config.crash_peak_margin:
            return peak_segment
        return incident_segment

    def _reduce_segment(self, segment: int) -> None:
        # Crash penalties do not touch accumulated_squared_updates: that
        # accumulator only tracks clean-lap increases, so a segment reduced
        # after a crash still gets a normal-sized learning rate to try again,
        # instead of being frozen near its floor forever.
        penalty = self.config.crash_penalty
        self.stages[segment] = max(self.config.minimum_stage, self.stages[segment] - penalty)
        self.crashes[segment] += 1
        self.clean_laps[segment] = 0
        self.cooldown_laps[segment] = self.config.crash_cooldown_laps

    def _apply_update(self, segment: int, update: float) -> None:
        self.stages[segment] = min(self.config.maximum_stage, self.stages[segment] + update)
        self.accumulated_squared_updates[segment] += update * update

    def _tick_cooldowns(self) -> None:
        for index, remaining in enumerate(self.cooldown_laps):
            if remaining > 0:
                self.cooldown_laps[index] = remaining - 1

    def _check_segment(self, segment: int) -> None:
        if not 0 <= segment < self.segment_count:
            raise IndexError(f"segment {segment} is outside 0..{self.segment_count - 1}.")


def create_initial_profile(graph: TrackGraph, config: TrainingConfig | None = None) -> SegmentProfile:
    """Create a conservative segment profile from graph curvature."""
    active_config = config or TrainingConfig()
    mean_curvature = _mean_curvature_by_segment(graph, active_config.segment_count)
    reference = _percentile(mean_curvature, active_config.corner_threshold_percentile)
    stages = []
    for curvature in mean_curvature:
        relative_curve = 0.0 if reference <= 0 else min(1.0, curvature / reference)
        stage = active_config.initial_stage - active_config.curvature_stage_reduction * relative_curve
        stages.append(max(active_config.minimum_stage, stage))
    preferred = _corner_exit_segments(mean_curvature, active_config)
    return SegmentProfile(
        stages=stages,
        accumulated_squared_updates=[0.0] * active_config.segment_count,
        clean_laps=[0] * active_config.segment_count,
        crashes=[0] * active_config.segment_count,
        incident_sites=[0] * active_config.segment_count,
        preferred_segments=preferred,
        config=active_config,
    )


def segment_for_node(node_index: int, node_count: int, segment_count: int) -> int:
    """Map an ordered graph node to an ordered profile segment."""
    if not 0 <= node_index < node_count:
        raise IndexError("node_index is outside the graph.")
    return min(segment_count - 1, node_index * segment_count // node_count)


def nearest_node_index(position: tuple[float, float], graph: TrackGraph) -> int:
    """Return the graph node nearest to an observed camera position."""
    if not graph.nodes:
        raise ValueError("graph must contain nodes.")
    return min(
        range(graph.node_count),
        key=lambda index: (graph.nodes[index].x - position[0]) ** 2
        + (graph.nodes[index].y - position[1]) ** 2,
    )


def segment_for_position(position: tuple[float, float], graph: TrackGraph, segment_count: int) -> int:
    """Map a camera position directly to the nearest training segment."""
    return segment_for_node(nearest_node_index(position, graph), graph.node_count, segment_count)


def save_profile(profile: SegmentProfile, path: str | Path) -> Path:
    """Persist a trainable profile and its learning statistics as JSON."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stages": profile.stages,
        "accumulated_squared_updates": profile.accumulated_squared_updates,
        "clean_laps": profile.clean_laps,
        "crashes": profile.crashes,
        "incident_sites": profile.incident_sites,
        "preferred_segments": profile.preferred_segments,
        "cooldown_laps": profile.cooldown_laps,
        "lap_count": profile.lap_count,
        "config": profile.config.__dict__,
    }
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output


def load_profile(path: str | Path) -> SegmentProfile:
    """Load a profile previously saved by :func:`save_profile`."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    config = TrainingConfig(**payload["config"])
    profile = SegmentProfile(
        stages=[float(value) for value in payload["stages"]],
        accumulated_squared_updates=[float(value) for value in payload["accumulated_squared_updates"]],
        clean_laps=[int(value) for value in payload["clean_laps"]],
        crashes=[int(value) for value in payload["crashes"]],
        incident_sites=[int(value) for value in payload.get("incident_sites", payload["crashes"])],
        preferred_segments=[int(value) for value in payload["preferred_segments"]],
        config=config,
        cooldown_laps=[int(value) for value in payload.get("cooldown_laps", [0] * config.segment_count)],
        lap_count=int(payload.get("lap_count", 0)),
    )
    if profile.segment_count != config.segment_count:
        raise ValueError("Profile data does not match its segment_count.")
    return profile


def _mean_curvature_by_segment(graph: TrackGraph, segment_count: int) -> list[float]:
    totals = [0.0] * segment_count
    counts = [0] * segment_count
    for node_index, node in enumerate(graph.nodes):
        segment = segment_for_node(node_index, graph.node_count, segment_count)
        totals[segment] += node.curvature
        counts[segment] += 1
    return [total / count if count else 0.0 for total, count in zip(totals, counts)]


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
    return ordered[index]


def _corner_exit_segments(mean_curvature: list[float], config: TrainingConfig) -> list[int]:
    threshold = _percentile(mean_curvature, config.corner_threshold_percentile)
    corner_segments = [index for index, curvature in enumerate(mean_curvature) if curvature >= threshold and curvature > 0]
    exits = {
        (corner + offset) % config.segment_count
        for corner in corner_segments
        for offset in range(1, config.corner_exit_segments + 1)
    }
    return sorted(exits)