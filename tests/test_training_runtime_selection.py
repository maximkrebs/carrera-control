import csv

from carrera_control.training_runtime import find_best_clean_profile


def test_find_best_clean_profile_selects_fastest_snapshot(tmp_path) -> None:
    run = tmp_path / "run"
    snapshots = run / "profile_snapshots"
    snapshots.mkdir(parents=True)
    with (run / "lap_times.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("lap", "lap_time_s", "best_lap_s", "updated_segment"))
        writer.writerow((1, 4.2, 4.2, 2))
        writer.writerow((2, 3.8, 3.8, 5))
    (snapshots / "lap-0001.json").write_text("{}", encoding="utf-8")
    (snapshots / "lap-0002.json").write_text("{}", encoding="utf-8")

    assert find_best_clean_profile(tmp_path).name == "lap-0002.json"