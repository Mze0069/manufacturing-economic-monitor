import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"
SERIES_ID = "IPMAN"
API_KEY_NAME = "FRED_API_KEY"
RAW_OUTPUT_PATH = Path("data/raw/ipman_observations_raw.json")
PROCESSED_OUTPUT_PATH = Path("data/processed/ipman_observations_processed.json")


class AppError(Exception):
    """User-facing application error."""


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise AppError(
            "Missing .env file. Create one in the project root with "
            f"{API_KEY_NAME}=your_fred_api_key."
        )

    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue

            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    except OSError as exc:
        raise AppError(f"Could not read .env file: {exc}") from exc

    return values


def get_api_key() -> str:
    api_key = load_env_file(Path(".env")).get(API_KEY_NAME, "").strip()
    if not api_key or api_key.lower() in {"your_fred_api_key", "replace_me"}:
        raise AppError(
            f"Missing FRED API key. Add {API_KEY_NAME}=your_fred_api_key "
            "to your .env file."
        )
    return api_key


def fetch_observations(api_key: str) -> dict:
    query = urlencode(
        {
            "series_id": SERIES_ID,
            "api_key": api_key,
            "file_type": "json",
        }
    )
    request_url = f"{FRED_API_URL}?{query}"

    try:
        with urlopen(request_url, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.reason or "FRED returned an HTTP error"
        raise AppError(
            f"FRED request failed with HTTP {exc.code}: {detail}. "
            "Check that your API key is valid and try again."
        ) from exc
    except URLError as exc:
        raise AppError(
            f"Could not connect to FRED: {exc.reason}. "
            "Check your internet connection and try again."
        ) from exc
    except TimeoutError as exc:
        raise AppError("FRED request timed out. Try again later.") from exc
    except json.JSONDecodeError as exc:
        raise AppError(
            "FRED returned a response that was not valid JSON. Try again later."
        ) from exc


def write_json(path: Path, payload: object) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise AppError(
            f"Could not write {path}. Check folder permissions and try again."
        ) from exc


def process_observations(payload: dict) -> list[dict[str, str]]:
    observations = payload.get("observations")
    if not isinstance(observations, list):
        raise AppError(
            "FRED response did not include an observations list. "
            "The API response format may have changed."
        )

    processed: list[dict[str, str]] = []
    for observation in observations:
        if not isinstance(observation, dict):
            continue

        date = observation.get("date")
        value = observation.get("value")
        if isinstance(date, str) and isinstance(value, str):
            processed.append({"date": date, "value": value})

    if not processed:
        raise AppError("No observations were found in the FRED response.")

    return processed


def latest_valid_observation(
    observations: list[dict[str, str]],
) -> tuple[str, str]:
    for observation in reversed(observations):
        date = observation["date"]
        value = observation["value"]
        try:
            Decimal(value)
        except InvalidOperation:
            continue

        return date, value

    raise AppError(
        "No valid manufacturing observations were available. "
        "FRED may have returned only placeholder values."
    )


def main() -> int:
    try:
        api_key = get_api_key()
        raw_payload = fetch_observations(api_key)
        write_json(RAW_OUTPUT_PATH, raw_payload)

        processed_observations = process_observations(raw_payload)
        write_json(PROCESSED_OUTPUT_PATH, processed_observations)

        latest_date, latest_value = latest_valid_observation(processed_observations)
        print(f"Latest manufacturing index: {latest_value} on {latest_date}")
        return 0
    except AppError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
