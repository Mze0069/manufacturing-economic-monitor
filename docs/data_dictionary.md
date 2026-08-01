# Data Dictionary

## Main structured output

The primary tabular output is:

`data/processed/manufacturing_economic_monitor.csv`

It is produced from validated FRED observations and contains one row per series and observation date.

| Field | Type | Meaning | Units or allowable values | Source and provenance | Missing-value rule | Transformation |
|---|---|---|---|---|---|---|
| `series_id` | string | FRED series identifier | `IPMAN`, `IPDMAN`, `IPNMAN`, `MCUMFN`, or `PCUOMFGOMFG` | Selected from the project's supported-series catalog and included in the FRED request | Never intentionally missing | Copied from validated request metadata |
| `series_name` | string | Human-readable indicator name | Text | Project series catalog derived from official FRED metadata | Never intentionally missing | Copied without numeric transformation |
| `units` | string | Measurement units for the original series | Examples include index values and percent | Project series catalog based on FRED series definitions | Never intentionally missing | Copied without transformation |
| `date` | ISO date | Observation month | `YYYY-MM-DD` | Validated FRED observation date | Invalid dates are rejected | Parsed as a date and exported in ISO format |
| `raw_value` | decimal text | Original numeric observation value | Series-specific original units | FRED API observation value after validation | FRED `.` placeholders are retained as missing values and are not treated as numeric | Numeric strings are preserved without rounding |
| `is_missing` | boolean | Whether the original FRED observation was missing | `true` or `false` | Derived from the validated `raw_value` | `true` when the FRED value is `.` | Boolean flag added during processing |
| `normalized_value` | decimal text or empty | Comparable index relative to the first valid observation for that series | First valid observation equals `100` | Derived from validated observations in the selected date range | Empty when the row is missing or normalization cannot be calculated | `raw_value / first_valid_value × 100` |

## Provenance and filters

- Source: Federal Reserve Economic Data (FRED) series-observations API.
- Report and final-project filter: observations from `2017-01-01` through the latest available observation in the preserved dataset.
- Selected series: `IPMAN`, `IPDMAN`, `IPNMAN`, `MCUMFN`, and `PCUOMFGOMFG`.
- Raw JSON responses are retained under `data/raw/`.
- Validated combined JSON and CSV outputs are retained under `data/processed/`.
- SQLite persistence is stored in `data/manufacturing_monitor.db`.

## Important interpretation notes

Original-unit values should only be compared directly when the units are compatible. The `normalized_value` field supports relative trend comparison by setting each series' first valid observation in the selected range to 100. Normalization does not change the underlying original values.
