import sys

from carrera_control import cli


def test_drive_forwards_web_port(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(cli, "run_autonomous_drive", lambda **kwargs: captured.update(kwargs) or "run")
    monkeypatch.setattr(sys, "argv", ["cli", "drive", "--track-graph", "graph.json", "--web-port", "8090"])
    cli.main()
    assert captured["web_port"] == 8090
