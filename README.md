# Manufacturing Economic Monitor

A small command-line workflow for fetching the FRED Industrial Production:
Manufacturing (`IPMAN`) series, preserving the raw API response, creating a
compact processed dataset, and printing the latest available manufacturing
index.

## Setup

1. Install `uv`.
2. Get a FRED API key from the Federal Reserve Economic Data site.
3. Create a local `.env` file in the project root:

```env
FRED_API_KEY=your_fred_api_key
```

4. Run the project:

```powershell
uv run main.py
```

The script writes the complete API response to
`data/raw/ipman_observations_raw.json` and processed date/value observations to
`data/processed/ipman_observations_processed.json`.

## FRED API

Documentation: https://fred.stlouisfed.org/docs/api/fred/series_observations.html

Example request:

```text
https://api.stlouisfed.org/fred/series/observations?series_id=IPMAN&api_key=YOUR_API_KEY&file_type=json
```
