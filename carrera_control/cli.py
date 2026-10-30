"""Command-line entry points for recognition, training, and autonomous driving."""

from __future__ import annotations

import argparse
from pathlib import Path

from .autonomous_drive import run_autonomous_drive
from .calibration_lap import record_calibration_lap
from .training_runtime import RuntimeConfig, run_training


def build_parser() -> argparse.ArgumentParser:
    """Build the Carrera AI command-line parser."""
    parser = argparse.ArgumentParser(description="Carrera Digital 132 camera controller")
    subparsers = parser.add_subparsers(dest="command", required=True)

    recognition = subparsers.add_parser("recognition-lap", help="record one path and build a TrackGraph")
    recognition.add_argument("--output-root", type=Path, default=Path("data/recognition_laps"))
    recognition.add_argument("--stage", type=int, default=5)
    recognition.add_argument("--timeout-s", type=float, default=120.0)
    recognition.add_argument("--port", default="COM4")
    recognition.add_argument("--camera-index", type=int, default=1)
    recognition.add_argument("--no-gui", action="store_true")

    train = subparsers.add_parser("train", help="train a stage profile on a TrackGraph")
    _add_drive_arguments(train)
    train.add_argument("--profile", type=Path)
    train.add_argument("--duration-s", type=float, default=1800.0)
    train.add_argument("--web-port", type=int)

    drive = subparsers.add_parser("drive", help="drive the fastest clean profile automatically")
    drive.add_argument("--track-graph", type=Path, required=True)
    drive.add_argument("--training-root", type=Path, default=Path("data/training_runs"))
    drive.add_argument("--output-root", type=Path, default=Path("data/drive_runs"))
    drive.add_argument("--profile", type=Path, help="optional explicit profile override")
    drive.add_argument("--duration-s", type=float, default=300.0)
    drive.add_argument("--port", default="COM4")
    drive.add_argument("--web-port", type=int)
    drive.add_argument("--no-gui", action="store_true")
    return parser


def _add_drive_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--track-graph", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("data/training_runs"))
    parser.add_argument("--port", default="COM4")
    parser.add_argument("--no-gui", action="store_true")


def main() -> None:
    """Run the selected command."""
    args = build_parser().parse_args()
    if args.command == "recognition-lap":
        run_dir = record_calibration_lap(
            output_root=args.output_root,
            stage=args.stage,
            timeout_s=args.timeout_s,
            camera_index=args.camera_index,
            port=args.port,
            show_gui=not args.no_gui,
        )
    elif args.command == "train":
        run_dir = run_training(
            track_graph_path=args.track_graph,
            output_root=args.output_root,
            profile_path=args.profile,
            runtime_config=RuntimeConfig(duration_s=args.duration_s),
            port=args.port,
            show_gui=not args.no_gui,
            web_port=args.web_port,
        )
    else:
        run_dir = run_autonomous_drive(
            track_graph_path=args.track_graph,
            training_root=args.training_root,
            output_root=args.output_root,
            profile_path=args.profile,
            duration_s=args.duration_s,
            port=args.port,
            show_gui=not args.no_gui,
            web_port=args.web_port,
        )
    print(f"Run saved to: {run_dir}")


if __name__ == "__main__":
    main()
