"""Drive a saved profile without changing it."""

from __future__ import annotations

from pathlib import Path

from .training import load_profile
from .training_runtime import RuntimeConfig, find_best_clean_profile, run_training


def run_autonomous_drive(
    track_graph_path: str | Path,
    training_root: str | Path,
    output_root: str | Path,
    profile_path: str | Path | None = None,
    duration_s: float = 300.0,
    port: str = "COM4",
    baudrate: int = 115200,
    show_gui: bool = True,
    web_port: int | None = None,
) -> Path:
    """Drive the fastest automatically discovered clean-lap profile.

    When ``profile_path`` is omitted, the fastest snapshot in ``training_root``
    is selected automatically. The current runtime keeps its safety handling;
    learning is disabled by using a frozen profile copy in this drive wrapper.
    """
    selected_profile = Path(profile_path) if profile_path is not None else find_best_clean_profile(training_root)
    profile = load_profile(selected_profile)
    return run_training(
        track_graph_path=track_graph_path,
        output_root=output_root,
        profile_path=selected_profile,
        training_config=profile.config,
        runtime_config=RuntimeConfig(duration_s=duration_s),
        port=port,
        baudrate=baudrate,
        show_gui=show_gui,
        learn=False,
        web_port=web_port,
    )
