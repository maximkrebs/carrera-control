import csv
import json

from carrera_control.calibration_lap import LapProgress, _write_run, lap_completed, lost_timeout_expired


def test_lap_requires_leaving_the_start_before_returning() -> None:
    progress = LapProgress()
    start = (100.0, 100.0)

    assert lap_completed(progress, (110.0, 100.0), start) is False
    assert progress.moved_away is False


def test_lap_completes_after_departure_and_return() -> None:
    progress = LapProgress()
    start = (100.0, 100.0)

    assert lap_completed(progress, (200.0, 100.0), start) is False
    assert progress.moved_away is True
    assert lap_completed(progress, (105.0, 100.0), start) is True


def test_vehicle_loss_expires_only_after_the_safety_timeout() -> None:
    assert lost_timeout_expired(None, now=2.0, timeout_s=0.5) is False
    assert lost_timeout_expired(1.0, now=1.4, timeout_s=0.5) is False
    assert lost_timeout_expired(1.0, now=1.5, timeout_s=0.5) is True


def test_incomplete_lap_persists_path_and_abort_reason(tmp_path) -> None:
    path = [(0.1, 100.0, 200.0, 42.0)]

    _write_run(
        tmp_path,
        path,
        completed=False,
        stage=5,
        camera_index=1,
        node_spacing_px=8.0,
        smoothing_window=5,
        stop_reason="vehicle_lost_off_track",
    )

    with (tmp_path / "path.csv").open(newline="", encoding="utf-8") as handle:
        assert list(csv.reader(handle)) == [
            ["elapsed_s", "x", "y", "area"],
            ["0.1", "100.0", "200.0", "42.0"],
        ]
    assert json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8")) == {
        "completed": False,
        "stage": 5,
        "camera_index": 1,
        "point_count": 1,
        "stop_reason": "vehicle_lost_off_track",
    }
    assert not (tmp_path / "track_graph.json").exists()