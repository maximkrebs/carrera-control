from carrera_control.calibration_lap import LapProgress, lap_completed, lost_timeout_expired


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