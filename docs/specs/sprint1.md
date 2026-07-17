# Sprint 1 Spec: Manufacturing Economic Monitor

## Problem statement

Economic monitoring often starts with a small number of trusted indicators, but manually retrieving and reshaping data slows down repeated analysis. This project needs a simple first workflow that can pull the Industrial Production: Manufacturing series from FRED, preserve the original API response, create a smaller processed dataset, and report the latest available manufacturing index.

## Sprint goal

Build the first runnable version of `manufacturing-economic-monitor` as a uv project that fetches the FRED `IPMAN` series, saves raw and processed JSON outputs, and prints a short latest-value summary from the command line.

## User requirements

- Read the FRED API key from a local `.env` file.
- Request the Federal Reserve Economic Data `IPMAN` series.
- Save the complete JSON response into `data/raw/`.
- Extract each observation's date and value into a processed JSON file in `data/processed/`.
- Print a short summary showing the latest manufacturing index and its observation date.
- Provide user-friendly error messages for common failure cases.
- Run with `uv run main.py`.

## Expected behavior

When the user runs `uv run main.py`, the application should:

1. Load configuration from `.env`.
2. Validate that a FRED API key is available.
3. Request the FRED observations endpoint for series `IPMAN`.
4. Save the complete API JSON response in `data/raw/`.
5. Transform the observations into a processed JSON file containing only observation dates and values.
6. Identify the latest valid observation.
7. Print a concise summary that includes the latest manufacturing index and observation date.

If the API key is missing, the API request fails, the response is invalid, the data directories cannot be written, or no valid observations are available, the application should print a clear message that explains the problem and how the user can address it.

## Plan

- Keep the first version as a small command-line script centered on `main.py`.
- Use `.env` for local configuration and avoid hardcoding secrets.
- Use the FRED API observations endpoint for `IPMAN`.
- Write raw API output before processing so the original response is available for debugging.
- Convert observations into a compact processed JSON structure.
- Treat missing or placeholder observation values as invalid for the latest-value summary.
- Keep error handling direct and readable for a beginner-friendly first sprint.

## Tasks

- Confirm project folders exist: `data/raw/`, `data/processed/`, and `docs/specs/`.
- Add dependency support for loading `.env` values if needed.
- Define the expected `.env` variable name for the FRED API key.
- Implement FRED API request logic for `IPMAN`.
- Save the full raw JSON response to `data/raw/`.
- Extract observation `date` and `value` fields into processed JSON.
- Save processed observations to `data/processed/`.
- Print the latest manufacturing index and observation date.
- Add user-friendly handling for missing API key, request errors, invalid JSON, missing observations, and file write errors.
- Verify the workflow with `uv run main.py`.

## Out of scope

- Charts, dashboards, or visualizations.
- Multiple FRED series.
- Scheduled or automated recurring runs.
- Database storage.
- Historical analysis beyond extracting dates and values.
- Forecasting or economic interpretation.
- Unit tests beyond any lightweight checks needed during implementation.
- Packaging or publishing the project.

## Definition of done

- `uv run main.py` completes successfully when a valid FRED API key is provided in `.env`.
- The app requests the `IPMAN` series from FRED.
- A complete raw JSON response is written to `data/raw/`.
- A processed JSON file with observation dates and values is written to `data/processed/`.
- The console prints the latest manufacturing index and observation date.
- Common setup, network, API, parsing, and file errors produce clear user-friendly messages.
- No API key or secret value is committed to the repository.
