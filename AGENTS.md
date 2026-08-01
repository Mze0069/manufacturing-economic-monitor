# AGENTS.md

## Project purpose

Manufacturing Economic Monitor is a Python CLI and Streamlit dashboard for retrieving, validating, storing, analyzing, and comparing supported FRED manufacturing indicators.

## Setup

Use Python 3.12 or newer and restore the locked environment with:

```bash
uv sync --dev
```

Live FRED refreshes require a local `.env` file containing:

```text
FRED_API_KEY=your_key_here
```

Never commit `.env`, API tokens, passwords, or other secrets.

## Important commands

Run tests:

```bash
uv run pytest
```

Run tests with the CI coverage threshold:

```bash
uv run pytest --cov=manufacturing_monitor --cov-fail-under=85
```

Run the CLI help:

```bash
uv run manufacturing-monitor --help
```

Run the dashboard:

```bash
uv run streamlit run src/manufacturing_monitor/dashboard.py
```

Render the Practicum 6 report:

```bash
uv run python reports/render_report.py
quarto render reports/manufacturing_report.qmd --to typst
```

## Repository navigation

- `src/manufacturing_monitor/` contains reusable application logic.
- `tests/` contains offline tests and committed fixtures.
- `data/raw/` contains preserved FRED response evidence.
- `data/processed/` contains validated and transformed project output.
- `docs/data_dictionary.md` defines the main structured output.
- `reports/manufacturing_report.qmd` is the authoritative report source.
- `reports/manufacturing_report.pdf` is the rendered report.
- `README.md` is the primary user-facing entry point.

## Conventions

- Reuse project functions instead of duplicating validation or analytics logic.
- Add type hints to function inputs and outputs.
- Use concise module, class, and function docstrings.
- Keep user-facing errors specific and actionable.
- Keep tests offline by mocking external requests and using committed fixtures.
- Do not edit generated PDFs manually; update the report source and rerender.
- Do not commit local logs, coverage output, virtual environments, or secrets.

## Sources of truth

- Package metadata and dependencies: `pyproject.toml`
- Locked dependency versions: `uv.lock`
- Supported FRED series: `src/manufacturing_monitor/series_catalog.py`
- Validation rules: `src/manufacturing_monitor/models.py`
- Shared application workflow: `src/manufacturing_monitor/workflow.py`
- Analytics definitions: `src/manufacturing_monitor/analytics.py`
- Output schema: `docs/data_dictionary.md`
