"""Small, deterministic helpers for safely approaching a CU stage profile."""

from __future__ import annotations


MIN_STAGE = 0
MAX_STAGE = 15
DEFAULT_DRIVE_STAGE = 4


def clamp_stage(stage: int | float) -> int:
    """Round and constrain a stage to the Pico/CU range ``0..15``."""
    return max(MIN_STAGE, min(MAX_STAGE, round(float(stage))))


def ramped_stage(
    target_stage: int | float,
    elapsed_s: float,
    ramp_duration_s: float = 4.0,
    start_stage: int | float = DEFAULT_DRIVE_STAGE,
) -> int:
    """Approach a target stage linearly over a configured slow-start duration.

    At ``elapsed_s == 0`` the result is the safe starting stage. At or after
    ``ramp_duration_s`` it is the target stage. The result is always an integer
    in the CU range ``0..15`` and never overshoots the target.

    If the target is below the starting stage, the function lowers the stage
    immediately rather than temporarily applying more throttle than requested.
    """
    target = clamp_stage(target_stage)
    start = clamp_stage(start_stage)
    if target <= start or ramp_duration_s <= 0 or elapsed_s >= ramp_duration_s:
        return target
    progress = max(0.0, elapsed_s) / ramp_duration_s
    return clamp_stage(start + (target - start) * progress)