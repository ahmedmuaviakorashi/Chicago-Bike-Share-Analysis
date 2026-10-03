from pathlib import Path

import pandas as pd

from bikeshare_analysis.pipeline import run_analysis

COLUMNS = [
    "ride_id",
    "rideable_type",
    "started_at",
    "ended_at",
    "start_station_name",
    "start_station_id",
    "end_station_name",
    "end_station_id",
    "start_lat",
    "start_lng",
    "end_lat",
    "end_lng",
    "member_casual",
]


def row(
    ride_id: str,
    start: str,
    end: str,
    rider: str,
    stations: bool = True,
) -> dict:
    return dict(
        zip(
            COLUMNS,
            [
                ride_id,
                "classic_bike",
                start,
                end,
                "Start" if stations else None,
                "S1" if stations else None,
                "End" if stations else None,
                "E1" if stations else None,
                41.9,
                -87.6,
                41.91,
                -87.61,
                rider,
            ],
        )
    )


def make_year(directory: Path) -> None:
    directory.mkdir(parents=True)
    january = [
        row("r1", "2024-01-01 08:00:00", "2024-01-01 08:10:00", "member"),
        row("r1", "2024-01-01 08:00:00", "2024-01-01 08:10:00", "member"),
        row("r2", "2024-01-06 12:00:00", "2024-01-06 12:30:00", "casual", False),
        row("r3", "2024-01-02 10:00:00", "2024-01-02 09:59:00", "member"),
        row("r4", "2024-01-02 10:00:00", "2024-01-03 10:01:00", "member"),
        row("r5", "2024-01-02 10:00:00", "2024-01-02 10:05:00", "subscriber"),
    ]
    pd.DataFrame(january, columns=COLUMNS).to_csv(
        directory / "202401-divvy-tripdata.csv", index=False
    )
    for month in range(2, 13):
        item = row(
            f"r{month + 4}",
            f"2024-{month:02d}-01 08:00:00",
            f"2024-{month:02d}-01 08:10:00",
            "member",
        )
        pd.DataFrame([item], columns=COLUMNS).to_csv(
            directory / f"2024{month:02d}-divvy-tripdata.csv", index=False
        )


def test_pipeline_retains_station_incomplete_rides(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    output = tmp_path / "artifacts"
    make_year(raw)
    result = run_analysis(raw, output)

    assert result["quality"] == {
        "raw_rows": 17,
        "duplicate_ride_id_rows": 1,
        "missing_ride_id_rows": 0,
        "invalid_member_type_rows": 1,
        "invalid_time_rows": 1,
        "over_24_hour_rows": 1,
        "station_incomplete_rows": 1,
        "outside_analysis_year_rows": 0,
        "valid_rows": 13,
    }
    summary = result["tables"]["rider_summary"].set_index("member_casual")
    assert summary.loc["casual", "rides"] == 1
    assert summary.loc["casual", "station_complete_rides"] == 0
    assert summary.loc["member", "rides"] == 12
    assert (output / "analysis.md").exists()
    assert (output / "figures" / "monthly_trips.png").exists()


def test_pipeline_requires_all_twelve_months(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    pd.DataFrame(columns=COLUMNS).to_csv(
        raw / "202401-divvy-tripdata.csv", index=False
    )
    try:
        run_analysis(raw, tmp_path / "artifacts")
    except FileNotFoundError as exc:
        assert "Expected 12" in str(exc)
    else:
        raise AssertionError("Expected missing months to be rejected")
