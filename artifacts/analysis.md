# 2024 Chicago bike-share analysis

## Validated dataset

- Raw rows: **5,860,568**
- Valid rides after ID, timestamp, membership, duration, and year checks: **5,852,081**
- Duplicate ride-ID rows: **211**
- Non-positive or missing-time rows: **723**
- Trips over 24 hours: **7,596**
- Rows without complete start/end station metadata: **1,652,259**

Station-incomplete rides remain in time, duration, membership, and bike-type analysis. They are excluded only from station and route rankings.
Quality categories can overlap and should not be subtracted independently from the raw total.

## Rider comparison

| Rider type | Rides | Share | Median duration | Mean duration | 90th percentile |
| --- | ---: | ---: | ---: | ---: | ---: |
| Casual | 2,145,151 | 36.66% | 12.02 min | 20.92 min | 42.87 min |
| Member | 3,706,930 | 63.34% | 8.68 min | 12.19 min | 23.88 min |

Casual riders take fewer trips but stay out longer. Members account for the larger share of rides and show a stronger utility pattern.

## Timing patterns

- Casual ridership peaks in month **9** and on **Saturday**.
- Member ridership peaks in month **9** and on **Wednesday**.
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
