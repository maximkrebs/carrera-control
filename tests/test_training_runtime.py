from carrera_control.training_runtime import forward_node_delta


def test_forward_node_delta_wraps_at_the_finish_line() -> None:
    assert forward_node_delta(98, 2, 100) == 4


def test_forward_node_delta_rejects_an_implausibly_large_jump() -> None:
    assert forward_node_delta(10, 80, 100) == 0

def test_lap_snapshot_holds_the_profile_that_drove_the_lap(tmp_path) -> None:
    import math

    from carrera_control.track_graph import build_track_graph
    from carrera_control.training import create_initial_profile, load_profile
    from carrera_control.training_runtime import RuntimeConfig, TrainingRunState, _update_lap_progress

    circle = [(200 + 100 * math.cos(2 * math.pi * i / 120), 200 + 100 * math.sin(2 * math.pi * i / 120)) for i in range(120)]
    profile = create_initial_profile(build_track_graph(circle))
    stages_during_lap = list(profile.stages)
    state = TrainingRunState(lap_started_at=0.0, previous_node=9, progress_nodes=9)
    snapshot_dir = tmp_path / "profile_snapshots"
    snapshot_dir.mkdir()

    _update_lap_progress(profile, state, tmp_path / "events.jsonl", tmp_path / "lap_times.csv", snapshot_dir,
                         now=10.0, elapsed=10.0, node_index=0, node_count=10, runtime=RuntimeConfig(), learn=True)

    assert load_profile(snapshot_dir / "lap-0001.json").stages == stages_during_lap
    assert profile.stages != stages_during_lap
