# Manufacturing Economic Monitor

[![CI](https://github.com/Mze0069/manufacturing-economic-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/Mze0069/manufacturing-economic-monitor/actions/workflows/ci.yml)

A Python command-line application and interactive Streamlit dashboard for collecting, validating, storing, analyzing, and comparing manufacturing indicators from the Federal Reserve Economic Data (FRED) API.

## Published package

The package is available on PyPI:

```bash
pip install manufacturing-economic-monitor
```

Verify the installation without contacting FRED:

```bash
manufacturing-monitor --project-info
```

Current package version: `0.2.0`

## Supported manufacturing indicators

- `IPMAN` — Industrial Production: Manufacturing
- `IPDMAN` — Industrial Production: Durable Manufacturing
- `IPNMAN` — Industrial Production: Nondurable Manufacturing
- `MCUMFN` — Capacity Utilization: Manufacturing
- `PCUOMFGOMFG` — Producer Price Index: Total Manufacturing Industries

## Main capabilities

- Retrieves real manufacturing data from the FRED API
- Validates API responses and observations with Pydantic
- Preserves one raw JSON response per selected series
- Produces validated combined JSON output
- Stores observations and fetch metadata in SQLite
- Reuses cached data without an API key or network connection
- Calculates latest value, month-over-month change, year-over-year change, minimum, maximum, mean, and missing-value counts
- Normalizes selected indicators to a common starting value of 100
- Exports combined normalized observations to CSV
- Provides an interactive Plotly and Streamlit dashboard
- Protects API keys from console output, logs, generated files, tests, and Git
- Runs offline tests through GitHub Actions on Python 3.12, 3.13, and 3.14

## Development setup

Clone the repository and install the locked development environment:

```bash
git clone https://github.com/Mze0069/manufacturing-economic-monitor.git
cd manufacturing-economic-monitor
uv sync --dev
```

Create a local `.env` file only when live FRED refreshes are needed:

```text
FRED_API_KEY=your_key_here
```

The `.env` file, generated datasets, databases, logs, coverage files, and distribution artifacts are ignored by Git.

## Command-line interface

Display project information without contacting FRED:

```bash
uv run manufacturing-monitor --project-info
```

Display all command options:

```bash
uv run manufacturing-monitor --help
```

Refresh all five supported indicators and export the normalized comparison:

```bash
uv run manufacturing-monitor \
  --series IPMAN \
  --series IPDMAN \
  --series IPNMAN \
  --series MCUMFN \
  --series PCUOMFGOMFG \
  --start-date 2017-01-01 \
  --refresh \
  --database data/manufacturing_monitor.db \
  --csv-output data/processed/manufacturing_economic_monitor.csv
```

Run the same selection from SQLite cache by omitting `--refresh`:

```bash
uv run manufacturing-monitor \
  --series IPMAN \
  --series IPDMAN \
  --series IPNMAN \
  --series MCUMFN \
  --series PCUOMFGOMFG \
  --start-date 2017-01-01 \
  --database data/manufacturing_monitor.db
```

## Interactive dashboard

Start the Streamlit application:

```bash
uv run streamlit run src/manufacturing_monitor/dashboard.py
```

The dashboard provides supported-series selection, optional date controls, cached loading, live refresh, source status, latest-value cards, original-unit charts, normalized comparison, summary statistics, recent observations, missing-value information, and CSV download.

Indicators with different original units are charted separately. The normalized comparison starts every selected series at 100.

## Generated evidence

A live run can create:

- one raw JSON response per selected FRED series
- one combined processed JSON file
- one SQLite database
- one normalized CSV export
- an optional operational log

Generated data is intentionally excluded from Git because it can be recreated from FRED or loaded from SQLite.

## Validation and failure handling

Incoming responses are validated before analysis. The application rejects:

- non-object top-level responses
- missing or invalid observation collections
- invalid dates
- unsupported series identifiers
- invalid numeric values other than the documented FRED `.` missing-value placeholder
- invalid or reversed date ranges
- live refresh attempts without an API key

Errors are presented through controlled application messages rather than uncontrolled tracebacks during normal CLI use.

## Tests and coverage

The tests use committed fixtures and mocks, so routine testing does not contact FRED:

```bash
uv run pytest
```

Run the same coverage requirement used by CI:

```bash
uv run pytest --cov=manufacturing_monitor --cov-fail-under=85
```

Final-project verification:

- 72 tests passing
- 86% total coverage
- offline tests
- Python 3.12, 3.13, and 3.14 CI matrix
- wheel and source-distribution validation with Twine

## Build the package

```bash
uv build
uv run twine check dist/*
```

The project produces both a Python wheel and source distribution.

## Security

- Never commit `.env` or API tokens.
- Never place an API key directly in committed commands or documentation.
- Logging excludes API keys and complete authenticated request URLs.
- Test fixtures use fake credentials and offline responses.
- PyPI credentials are used only through secure password prompts.

## Project documentation

- [Open-source license](LICENSE)
- [Contributor and agent guidance](AGENTS.md)
- [Data dictionary](docs/data_dictionary.md)
- [Authoritative Quarto report source](reports/manufacturing_report.qmd)
- [Rendered reproducible report](reports/manufacturing_report.pdf)

## Author

Mohammadreza Ensafi
Auburn University
