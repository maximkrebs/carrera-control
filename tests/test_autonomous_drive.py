from pathlib import Path

from carrera_control import autonomous_drive


def test_drive_can_resolve_a_profile_automatically(monkeypatch, tmp_path) -> None:
    selected = tmp_path / "best.json"
    selected.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(autonomous_drive, "find_best_clean_profile", lambda _root: selected)
    monkeypatch.setattr(autonomous_drive, "load_profile", lambda _path: type("Profile", (), {"config": object()})())
    captured = {}
    monkeypatch.setattr(autonomous_drive, "run_training", lambda **kwargs: captured.update(kwargs) or Path("run"))

    result = autonomous_drive.run_autonomous_drive("graph.json", tmp_path, tmp_path / "out")

    assert result == Path("run")
    assert captured["profile_path"] == selected
    assert captured["learn"] is False