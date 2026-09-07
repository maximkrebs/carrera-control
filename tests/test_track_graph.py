import json
from math import cos, sin, tau

from carrera_control.track_graph import build_track_graph, load_track_graph, save_track_graph


def _circle_samples(radius: float = 100.0, count: int = 80) -> list[tuple[float, float]]:
    return [(radius * cos(tau * index / count), radius * sin(tau * index / count)) for index in range(count)]


def test_build_track_graph_returns_evenly_spaced_closed_nodes() -> None:
    graph = build_track_graph(_circle_samples(), node_spacing_px=10, smoothing_window=5)

    assert graph.closed is True
    assert graph.node_count >= 50
    assert 600 < graph.track_length_px < 700
    assert all(node.curvature >= 0 for node in graph.nodes)


def test_track_graph_round_trips_as_json(tmp_path) -> None:
    graph = build_track_graph(_circle_samples(), node_spacing_px=12)
    output = save_track_graph(graph, tmp_path / "track_graph.json")

    loaded = load_track_graph(output)

    assert loaded.node_count == graph.node_count
    assert loaded.track_length_px == graph.track_length_px
    assert json.loads(output.read_text(encoding="utf-8"))["closed"] is True


def test_load_track_graph_accepts_legacy_calibration_metadata(tmp_path) -> None:
    path = tmp_path / "legacy-track-graph.json"
    path.write_text(
        json.dumps(
            {
                "track_length_px": 30.0,
                "node_count": 3,
                "nodes": [
                    {"x": 0.0, "y": 0.0, "curvature": 0.0},
                    {"x": 10.0, "y": 0.0, "curvature": 0.1},
                    {"x": 20.0, "y": 0.0, "curvature": 0.0},
                ],
            }
        ),
        encoding="utf-8",
    )

    graph = load_track_graph(path)

    assert graph.closed is True
    assert graph.node_spacing_px == 10.0
    assert graph.smoothing_window == 1