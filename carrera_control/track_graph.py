"""Build and persist an ordered track graph from one recognition-lap path."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from math import atan2, hypot, pi
from pathlib import Path
from typing import Iterable, Sequence


Point = tuple[float, float]
PathRow = tuple[float, float, float, float]


@dataclass(frozen=True)
class TrackNode:
    """One equally spaced point on the closed driven line."""

    x: float
    y: float
    curvature: float


@dataclass(frozen=True)
class TrackGraph:
    """Ordered, closed representation of the driven track line."""

    nodes: tuple[TrackNode, ...]
    track_length_px: float
    node_spacing_px: float
    smoothing_window: int
    closed: bool = True

    @property
    def node_count(self) -> int:
        """Return the number of nodes in the cyclic graph."""
        return len(self.nodes)


def build_track_graph(
    path: Sequence[Point] | Sequence[PathRow],
    node_spacing_px: float = 8.0,
    smoothing_window: int = 5,
) -> TrackGraph:
    """Create a closed graph from time-ordered recognition-lap samples.

    The input order is preserved. Samples are first smoothed along the driven
    line, then resampled by travelled distance so graph nodes are comparable
    even when camera frame timing is uneven. The final segment connects the
    last node back to the first node.
    """
    if node_spacing_px <= 0:
        raise ValueError("node_spacing_px must be greater than zero.")
    if smoothing_window < 1 or smoothing_window % 2 == 0:
        raise ValueError("smoothing_window must be a positive odd number.")
    points = _extract_points(path)
    points = _remove_consecutive_duplicates(points)
    if len(points) < 3:
        raise ValueError("At least three distinct path points are required.")
    smoothed = _smooth_closed_path(points, smoothing_window)
    sampled, track_length = _resample_closed_path(smoothed, node_spacing_px)
    nodes = tuple(
        TrackNode(x=point[0], y=point[1], curvature=_curvature_at(sampled, index))
        for index, point in enumerate(sampled)
    )
    return TrackGraph(nodes, track_length, node_spacing_px, smoothing_window)


def build_track_graph_from_csv(
    path_csv: str | Path,
    node_spacing_px: float = 8.0,
    smoothing_window: int = 5,
) -> TrackGraph:
    """Load ``path.csv`` produced by a recognition lap and build its graph."""
    with Path(path_csv).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    path = [
        (float(row["elapsed_s"]), float(row["x"]), float(row["y"]), float(row["area"]))
        for row in rows
    ]
    return build_track_graph(path, node_spacing_px, smoothing_window)


def save_track_graph(graph: TrackGraph, output_path: str | Path) -> Path:
    """Write a graph as readable JSON and return its path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "closed": graph.closed,
        "node_count": graph.node_count,
        "track_length_px": graph.track_length_px,
        "node_spacing_px": graph.node_spacing_px,
        "smoothing_window": graph.smoothing_window,
        "nodes": [
            {"x": node.x, "y": node.y, "curvature": node.curvature}
            for node in graph.nodes
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def load_track_graph(path: str | Path) -> TrackGraph:
    """Load a graph previously written by :func:`save_track_graph`."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    nodes = tuple(TrackNode(float(item["x"]), float(item["y"]), float(item["curvature"])) for item in payload["nodes"])
    # Older calibration graphs predate the explicit metadata fields but already
    # represented a cyclic driven lap. Preserve those files as closed graphs.
    if len(nodes) < 3 or payload.get("closed", True) is not True:
        raise ValueError("Track graph must contain at least three closed nodes.")
    return TrackGraph(
        nodes=nodes,
        track_length_px=float(payload["track_length_px"]),
        node_spacing_px=float(payload.get("node_spacing_px", payload["track_length_px"] / len(nodes))),
        smoothing_window=int(payload.get("smoothing_window", 1)),
        closed=True,
    )


def _extract_points(path: Sequence[Point] | Sequence[PathRow]) -> list[Point]:
    points: list[Point] = []
    for sample in path:
        if len(sample) < 2:
            raise ValueError("Every path sample needs x and y coordinates.")
        if len(sample) == 2:
            points.append((float(sample[0]), float(sample[1])))
        else:
            points.append((float(sample[1]), float(sample[2])))
    return points


def _remove_consecutive_duplicates(points: Iterable[Point]) -> list[Point]:
    result: list[Point] = []
    for point in points:
        if not result or point != result[-1]:
            result.append(point)
    if len(result) > 1 and result[0] == result[-1]:
        result.pop()
    return result


def _smooth_closed_path(points: list[Point], window: int) -> list[Point]:
    radius = window // 2
    smoothed: list[Point] = []
    for index in range(len(points)):
        neighborhood = [points[(index + offset) % len(points)] for offset in range(-radius, radius + 1)]
        smoothed.append((sum(point[0] for point in neighborhood) / len(neighborhood), sum(point[1] for point in neighborhood) / len(neighborhood)))
    return smoothed


def _resample_closed_path(points: list[Point], spacing: float) -> tuple[list[Point], float]:
    segment_lengths = [hypot(points[(index + 1) % len(points)][0] - point[0], points[(index + 1) % len(points)][1] - point[1]) for index, point in enumerate(points)]
    total_length = sum(segment_lengths)
    if total_length < spacing * 3:
        raise ValueError("Path is too short for the requested node spacing.")
    node_count = max(3, round(total_length / spacing))
    targets = [total_length * index / node_count for index in range(node_count)]
    sampled: list[Point] = []
    segment_start_distance = 0.0
    segment_index = 0
    for target in targets:
        while segment_index < len(segment_lengths) - 1 and target > segment_start_distance + segment_lengths[segment_index]:
            segment_start_distance += segment_lengths[segment_index]
            segment_index += 1
        segment_length = segment_lengths[segment_index]
        fraction = 0.0 if segment_length == 0 else (target - segment_start_distance) / segment_length
        start = points[segment_index]
        end = points[(segment_index + 1) % len(points)]
        sampled.append((start[0] + fraction * (end[0] - start[0]), start[1] + fraction * (end[1] - start[1])))
    return sampled, total_length


def _curvature_at(points: list[Point], index: int) -> float:
    previous = points[(index - 1) % len(points)]
    current = points[index]
    following = points[(index + 1) % len(points)]
    incoming_angle = atan2(current[1] - previous[1], current[0] - previous[0])
    outgoing_angle = atan2(following[1] - current[1], following[0] - current[0])
    turn = (outgoing_angle - incoming_angle + pi) % (2 * pi) - pi
    length = (hypot(current[0] - previous[0], current[1] - previous[1]) + hypot(following[0] - current[0], following[1] - current[1])) / 2
    return abs(turn) / length if length else 0.0