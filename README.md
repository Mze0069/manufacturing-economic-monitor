# Manufacturing Economic Monitor

A small CLI and Streamlit dashboard for fetching the FRED Industrial Production:
Manufacturing (`IPMAN`) series, validating the response, saving raw and processed
JSON files, and showing the latest valid manufacturing index.

## Setup

Install dependencies:

```powershell
uv sync
```

Create a local `.env` file from the committed example:

```env
FRED_API_KEY=your_fred_api_key
```

`.env` is ignored by Git. Do not commit API keys or downloaded live data.

## Tests

Run the fixture-backed test suite:

```powershell
uv run pytest
```

Run tests with coverage:

```powershell
uv run pytest --cov=manufacturing_monitor
```

Tests use committed files in `tests/fixtures/` and mocks/monkeypatching for
external behavior. Routine tests do not contact the live FRED API.

## CLI

Run the installed command:

```powershell
uv run manufacturing-monitor
```

The compatibility wrapper still works:

```powershell
uv run main.py
```

Default output files are:

- raw response: `data/raw/ipman_observations_raw.json`
- processed observations: `data/processed/ipman_observations_processed.json`

Run without contacting FRED:

```powershell
uv run manufacturing-monitor --project-info
```

Enable console diagnostics:

```powershell
uv run manufacturing-monitor --verbose
```

Write detailed diagnostics to a log file:

```powershell
uv run manufacturing-monitor --log-file logs/manufacturing-monitor.log
```

Default behavior does not print diagnostic logs. Logging records request events,
validation, saved-file locations, and failures, but not API keys or complete
request URLs.

## Dashboard

Run the Streamlit dashboard:

```powershell
uv run streamlit run src/manufacturing_monitor/dashboard.py
```

The dashboard uses the same API, Pydantic validation, and workflow code as the
CLI. It accepts a FRED API key through a password-style input and also allows the
local environment key from `.env`.

## Validation

Incoming FRED responses are validated with Pydantic before the app uses them.
The app rejects:

- non-object top-level responses
- missing or invalid `observations`
- invalid observation dates
- observation values that are neither numeric strings nor the known FRED `.`
  placeholder

Placeholder values are preserved in processed output but skipped when selecting
the latest valid manufacturing index.
