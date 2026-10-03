import argparse
import json
from pathlib import Path
from typing import Any

import duckdb
import matplotlib.pyplot as plt
import pandas as pd

plt.switch_backend("Agg")

EXPECTED_COLUMNS = {
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
}


def _sql_paths(paths: list[Path]) -> str:
    escaped = ["'" + path.resolve().as_posix().replace("'", "''") + "'" for path in paths]
    return "[" + ", ".join(escaped) + "]"


def _write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _build_views(connection: duckdb.DuckDBPyConnection, csv_files: list[Path], year: int) -> None:
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW raw_rides AS
        SELECT *
        FROM read_csv_auto(
            {_sql_paths(csv_files)},
            header = true,
            union_by_name = true,
            timestampformat = '%Y-%m-%d %H:%M:%S'
        )
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info('raw_rides')").fetchall()}
    missing = EXPECTED_COLUMNS - columns
    if missing:
        raise ValueError("Missing required columns: " + ", ".join(sorted(missing)))

    connection.execute(
        """
        CREATE OR REPLACE TEMP VIEW staged_rides AS
        SELECT
            *,
            DATE_DIFF('second', started_at, ended_at) AS duration_seconds
        FROM raw_rides
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW eligible_rides AS
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY ride_id
                ORDER BY started_at, ended_at, rideable_type
            ) AS duplicate_rank
        FROM staged_rides
        WHERE ride_id IS NOT NULL
          AND TRIM(ride_id) <> ''
          AND member_casual IN ('member', 'casual')
          AND started_at IS NOT NULL
          AND ended_at IS NOT NULL
          AND EXTRACT('year' FROM started_at) = {year}
          AND duration_seconds > 0
          AND duration_seconds <= 86400
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP VIEW valid_rides AS
        SELECT
            ride_id,
            rideable_type,
            started_at,
            ended_at,
            start_station_name,
            start_station_id,
            end_station_name,
            end_station_id,
            start_lat,
            start_lng,
            end_lat,
            end_lng,
            member_casual,
            duration_seconds / 60.0 AS duration_minutes,
            EXTRACT('month' FROM started_at)::INTEGER AS month,
            EXTRACT('isodow' FROM started_at)::INTEGER AS iso_weekday,
            STRFTIME(started_at, '%A') AS weekday,
            EXTRACT('hour' FROM started_at)::INTEGER AS start_hour,
            start_station_name IS NOT NULL
                AND end_station_name IS NOT NULL
                AND start_station_id IS NOT NULL
                AND end_station_id IS NOT NULL AS station_complete
        FROM eligible_rides
        WHERE duplicate_rank = 1
        """
    )


def _quality_summary(connection: duckdb.DuckDBPyConnection, year: int) -> dict[str, int]:
    query = f"""
    SELECT
        COUNT(*)::BIGINT AS raw_rows,
        COUNT(*) - COUNT(DISTINCT ride_id) AS duplicate_ride_id_rows,
        COUNT(*) FILTER (WHERE ride_id IS NULL OR TRIM(ride_id) = '') AS missing_ride_id_rows,
        COUNT(*) FILTER (WHERE member_casual NOT IN ('member', 'casual') OR member_casual IS NULL)
            AS invalid_member_type_rows,
        COUNT(*) FILTER (
            WHERE started_at IS NULL OR ended_at IS NULL OR ended_at <= started_at
        ) AS invalid_time_rows,
        COUNT(*) FILTER (
            WHERE started_at IS NOT NULL
              AND ended_at IS NOT NULL
              AND DATE_DIFF('second', started_at, ended_at) > 86400
        ) AS over_24_hour_rows,
        COUNT(*) FILTER (
            WHERE start_station_name IS NULL
               OR end_station_name IS NULL
               OR start_station_id IS NULL
               OR end_station_id IS NULL
        ) AS station_incomplete_rows,
        COUNT(*) FILTER (
            WHERE started_at IS NOT NULL AND EXTRACT('year' FROM started_at) <> {year}
        ) AS outside_analysis_year_rows,
        (SELECT COUNT(*) FROM valid_rides)::BIGINT AS valid_rows
    FROM raw_rides
    """
    row = connection.execute(query).fetchone()
    columns = [item[0] for item in connection.description]
    return {column: int(value) for column, value in zip(columns, row)}


def _tables(connection: duckdb.DuckDBPyConnection) -> dict[str, pd.DataFrame]:
    return {
        "rider_summary": connection.execute(
            """
            SELECT
                member_casual,
                COUNT(*)::BIGINT AS rides,
                ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS ride_share_percent,
                ROUND(MEDIAN(duration_minutes), 2) AS median_duration_minutes,
                ROUND(AVG(duration_minutes), 2) AS mean_duration_minutes,
                ROUND(QUANTILE_CONT(duration_minutes, 0.9), 2) AS p90_duration_minutes,
                COUNT(*) FILTER (WHERE station_complete)::BIGINT AS station_complete_rides,
                ROUND(100.0 * COUNT(*) FILTER (WHERE station_complete) / COUNT(*), 2)
                    AS station_complete_percent
            FROM valid_rides
            GROUP BY member_casual
            ORDER BY member_casual
            """
        ).df(),
        "monthly_rides": connection.execute(
            """
            SELECT month, member_casual, COUNT(*)::BIGINT AS rides
            FROM valid_rides
            GROUP BY month, member_casual
            ORDER BY month, member_casual
            """
        ).df(),
        "weekday_rides": connection.execute(
            """
            SELECT iso_weekday, weekday, member_casual, COUNT(*)::BIGINT AS rides
            FROM valid_rides
            GROUP BY iso_weekday, weekday, member_casual
            ORDER BY iso_weekday, member_casual
            """
        ).df(),
        "hourly_rides": connection.execute(
            """
            SELECT start_hour, member_casual, COUNT(*)::BIGINT AS rides
            FROM valid_rides
            GROUP BY start_hour, member_casual
            ORDER BY start_hour, member_casual
            """
        ).df(),
        "rideable_type": connection.execute(
            """
            SELECT rideable_type, member_casual, COUNT(*)::BIGINT AS rides
            FROM valid_rides
            GROUP BY rideable_type, member_casual
            ORDER BY rideable_type, member_casual
            """
        ).df(),
        "top_start_stations": connection.execute(
            """
            SELECT member_casual, start_station_name, COUNT(*)::BIGINT AS rides
            FROM valid_rides
            WHERE station_complete
            GROUP BY member_casual, start_station_name
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY member_casual ORDER BY COUNT(*) DESC, start_station_name
            ) <= 10
            ORDER BY member_casual, rides DESC, start_station_name
            """
        ).df(),
        "top_routes": connection.execute(
            """
            SELECT
                member_casual,
                start_station_name,
                end_station_name,
                COUNT(*)::BIGINT AS rides
            FROM valid_rides
            WHERE station_complete
            GROUP BY member_casual, start_station_name, end_station_name
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY member_casual
                ORDER BY COUNT(*) DESC, start_station_name, end_station_name
            ) <= 10
            ORDER BY member_casual, rides DESC, start_station_name, end_station_name
            """
        ).df(),
    }


def _line_chart(
    frame: pd.DataFrame,
    x: str,
    title: str,
    x_label: str,
    output: Path,
) -> None:
    pivot = frame.pivot(index=x, columns="member_casual", values="rides")
    ax = pivot.plot(marker="o", figsize=(9, 5), color={"casual": "#e76f51", "member": "#2a9d8f"})
    ax.set_title(title)
    ax.set_xlabel(x_label)
    ax.set_ylabel("Rides")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(title="Rider type")
    ax.get_figure().tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    ax.get_figure().savefig(output, dpi=160)
    plt.close(ax.get_figure())


def _weekday_chart(frame: pd.DataFrame, output: Path) -> None:
    ordered = frame.sort_values("iso_weekday")
    pivot = ordered.pivot(index="weekday", columns="member_casual", values="rides")
    order = ordered.drop_duplicates("iso_weekday")["weekday"].tolist()
    ax = pivot.reindex(order).plot.bar(
        figsize=(9, 5), color={"casual": "#e76f51", "member": "#2a9d8f"}
    )
    ax.set_title("Trips by weekday and rider type")
    ax.set_xlabel("")
    ax.set_ylabel("Rides")
    ax.tick_params(axis="x", rotation=25)
    ax.legend(title="Rider type")
    ax.get_figure().tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    ax.get_figure().savefig(output, dpi=160)
    plt.close(ax.get_figure())


def _duration_chart(frame: pd.DataFrame, output: Path) -> None:
    chart = frame.set_index("member_casual")[
        ["median_duration_minutes", "mean_duration_minutes"]
    ].rename(
        columns={
            "median_duration_minutes": "Median",
            "mean_duration_minutes": "Mean",
        }
    )
    ax = chart.plot.bar(figsize=(7, 5), color=["#264653", "#f4a261"])
    ax.set_title("Trip duration by rider type")
    ax.set_xlabel("")
    ax.set_ylabel("Minutes")
    ax.tick_params(axis="x", rotation=0)
    ax.get_figure().tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    ax.get_figure().savefig(output, dpi=160)
    plt.close(ax.get_figure())


def _report(year: int, quality: dict[str, int], tables: dict[str, pd.DataFrame]) -> str:
    summary = tables["rider_summary"].set_index("member_casual")
    casual = summary.loc["casual"]
    member = summary.loc["member"]
    monthly = tables["monthly_rides"]
    weekday = tables["weekday_rides"]
    casual_peak_month = monthly[monthly["member_casual"] == "casual"].sort_values("rides").iloc[-1]
    member_peak_month = monthly[monthly["member_casual"] == "member"].sort_values("rides").iloc[-1]
    casual_peak_day = weekday[weekday["member_casual"] == "casual"].sort_values("rides").iloc[-1]
    member_peak_day = weekday[weekday["member_casual"] == "member"].sort_values("rides").iloc[-1]

    return f"""# {year} Chicago bike-share analysis

## Validated dataset

- Raw rows: **{quality['raw_rows']:,}**
- Valid rides after ID, timestamp, membership, duration, and year checks: **{quality['valid_rows']:,}**
- Duplicate ride-ID rows: **{quality['duplicate_ride_id_rows']:,}**
- Non-positive or missing-time rows: **{quality['invalid_time_rows']:,}**
- Trips over 24 hours: **{quality['over_24_hour_rows']:,}**
- Rows without complete start/end station metadata: **{quality['station_incomplete_rows']:,}**

Station-incomplete rides remain in time, duration, membership, and bike-type analysis. They are excluded only from station and route rankings.
Quality categories can overlap and should not be subtracted independently from the raw total.

## Rider comparison

| Rider type | Rides | Share | Median duration | Mean duration | 90th percentile |
| --- | ---: | ---: | ---: | ---: | ---: |
| Casual | {int(casual['rides']):,} | {casual['ride_share_percent']:.2f}% | {casual['median_duration_minutes']:.2f} min | {casual['mean_duration_minutes']:.2f} min | {casual['p90_duration_minutes']:.2f} min |
| Member | {int(member['rides']):,} | {member['ride_share_percent']:.2f}% | {member['median_duration_minutes']:.2f} min | {member['mean_duration_minutes']:.2f} min | {member['p90_duration_minutes']:.2f} min |

Casual riders take fewer trips but stay out longer. Members account for the larger share of rides and show a stronger utility pattern.

## Timing patterns

- Casual ridership peaks in month **{int(casual_peak_month['month'])}** and on **{casual_peak_day['weekday']}**.
- Member ridership peaks in month **{int(member_peak_month['month'])}** and on **{member_peak_day['weekday']}**.
- Hourly and weekday tables are published under `artifacts/tables` so the commuting and leisure interpretation can be inspected directly.

## Recommendations

1. Target high-volume warm-season and weekend periods with a clearly priced membership trial.
2. Compare an annual membership against observed casual trip frequency in campaign messaging, without claiming individual-level savings from anonymous trip records.
3. Use scenic stations and routes only for geographically targeted creative; station-null rides mean those rankings do not represent the full population.
4. Test conversion offers experimentally. Trip records describe behavior but do not identify which casual riders later purchase memberships.

## Limits

- The data is trip-level, not rider-level; repeat trips cannot be linked to one person.
- Missing station metadata is not random, particularly for dockless-capable bikes.
- Trips longer than 24 hours are excluded as operational or docking outliers.
- Time patterns support commuting or leisure hypotheses but do not prove trip purpose.
- Published route rankings use only rides with complete station names and IDs.
"""


def run_analysis(
    raw_directory: Path,
    output_directory: Path,
    year: int = 2024,
) -> dict[str, Any]:
    csv_files = sorted(raw_directory.glob(f"{year}[0-1][0-9]-divvy-tripdata.csv"))
    if len(csv_files) != 12:
        raise FileNotFoundError(
            f"Expected 12 monthly CSV files for {year} in {raw_directory}; found {len(csv_files)}."
        )

    connection = duckdb.connect()
    try:
        _build_views(connection, csv_files, year)
        quality = _quality_summary(connection, year)
        tables = _tables(connection)
    finally:
        connection.close()

    table_directory = output_directory / "tables"
    for name, frame in tables.items():
        _write_table(frame, table_directory / f"{name}.csv")

    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "quality_summary.json").write_text(
        json.dumps(quality, indent=2), encoding="utf-8"
    )
    (output_directory / "analysis.md").write_text(
        _report(year, quality, tables), encoding="utf-8"
    )

    figure_directory = output_directory / "figures"
    _line_chart(
        tables["monthly_rides"],
        "month",
        "Monthly trips by rider type",
        "Month",
        figure_directory / "monthly_trips.png",
    )
    _line_chart(
        tables["hourly_rides"],
        "start_hour",
        "Trips by starting hour and rider type",
        "Starting hour",
        figure_directory / "hourly_trips.png",
    )
    _weekday_chart(tables["weekday_rides"], figure_directory / "weekday_trips.png")
    _duration_chart(tables["rider_summary"], figure_directory / "trip_duration.png")
    return {"quality": quality, "tables": tables}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Chicago bike-share analysis.")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--year", type=int, default=2024)
    args = parser.parse_args()
    result = run_analysis(args.raw_dir, args.output_dir, args.year)
    print(json.dumps(result["quality"], indent=2))


if __name__ == "__main__":
    main()
