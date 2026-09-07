from carrera_control.stage_control import ramped_stage


def test_ramped_stage_reaches_profile_target_after_four_seconds() -> None:
    assert ramped_stage(target_stage=12, elapsed_s=0.0) == 4
    assert ramped_stage(target_stage=12, elapsed_s=2.0) == 8
    assert ramped_stage(target_stage=12, elapsed_s=4.0) == 12


def test_ramped_stage_clamps_elapsed_time_and_never_overshoots() -> None:
    assert ramped_stage(target_stage=12, elapsed_s=-1.0) == 4
    assert ramped_stage(target_stage=12, elapsed_s=8.0) == 12
    assert ramped_stage(target_stage=3, elapsed_s=1.0) == 3


def test_ramped_stage_can_be_configured_for_a_different_start_and_duration() -> None:
    assert ramped_stage(target_stage=15, elapsed_s=1.0, ramp_duration_s=5.0, start_stage=5) == 7