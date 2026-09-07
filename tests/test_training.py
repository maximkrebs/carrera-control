from carrera_control.track_graph import TrackGraph, TrackNode
from carrera_control.training import (
    TrainingConfig,
    create_initial_profile,
    load_profile,
    save_profile,
    segment_for_node,
    segment_for_position,
)


def test_initial_profile_is_conservative_and_prefers_corner_exits() -> None:
    graph = TrackGraph(
        nodes=tuple(TrackNode(float(index), 0.0, 1.0 if index in {4, 5} else 0.0) for index in range(12)),
        track_length_px=12.0,
        node_spacing_px=1.0,
        smoothing_window=1,
    )
    profile = create_initial_profile(graph, TrainingConfig(segment_count=4, initial_stage=5, maximum_stage=12))

    assert all(5 <= stage <= 7 for stage in profile.stages)
    assert 2 in profile.preferred_segments


def test_clean_laps_raise_one_preferred_segment_with_decreasing_learning_rate() -> None:
    graph = TrackGraph(
        nodes=tuple(TrackNode(float(index), 0.0, 0.0) for index in range(12)),
        track_length_px=12.0,
        node_spacing_px=1.0,
        smoothing_window=1,
    )
    profile = create_initial_profile(graph, TrainingConfig(segment_count=4, base_learning_rate=1.0))
    first = profile.record_clean_lap()
    first_stage = profile.stages[first]
    second = profile.record_clean_lap()

    assert first is not None
    assert second is not None
    assert profile.stages[first] == first_stage
    assert profile.learning_rate(first) < 1.0


def test_crash_lowers_segment_and_profile_round_trips(tmp_path) -> None:
    graph = TrackGraph(
        nodes=tuple(TrackNode(float(index), 0.0, 0.0) for index in range(12)),
        track_length_px=12.0,
        node_spacing_px=1.0,
        smoothing_window=1,
    )
    profile = create_initial_profile(graph, TrainingConfig(segment_count=4))
    before = profile.stages[1]
    profile.record_crash(1)
    path = save_profile(profile, tmp_path / "profile.json")
    loaded = load_profile(path)

    assert loaded.stages[1] < before
    assert loaded.crashes[1] == 1
    assert segment_for_node(11, 12, 4) == 3


def test_repeated_crashes_search_further_back_for_the_highest_speed_peak() -> None:
    graph = TrackGraph(
        nodes=tuple(TrackNode(float(index), 0.0, 0.0) for index in range(18)),
        track_length_px=18.0,
        node_spacing_px=1.0,
        smoothing_window=1,
    )
    config = TrainingConfig(
        segment_count=6,
        initial_stage=5,
        maximum_stage=15,
        crash_search_window_segments=2,
        crash_search_expansion_segments=2,
    )
    profile = create_initial_profile(graph, config)
    profile.stages[:] = [11.0, 12.0, 6.0, 5.0, 5.0, 5.0]

    first_cause = profile.record_crash(4)
    second_cause = profile.record_crash(4)

    assert first_cause == 2
    assert second_cause == 1
    assert profile.incident_sites[4] == 2
    assert profile.crashes[2] == 1
    assert profile.crashes[1] == 1


def test_position_maps_to_the_nearest_training_segment() -> None:
    graph = TrackGraph(
        nodes=tuple(TrackNode(float(index), 0.0, 0.0) for index in range(12)),
        track_length_px=12.0,
        node_spacing_px=1.0,
        smoothing_window=1,
    )

    assert segment_for_position((10.2, 0.1), graph, 4) == 3