from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import sqlite3
from pathlib import Path

from manufacturing_monitor.series_catalog import SUPPORTED_SERIES, SupportedSeries, is_supported_series


DEFAULT_DATABASE_PATH = Path("data/manufacturing_monitor.db")
FETCH_SOURCE_LIVE = "live"
FETCH_SOURCE_FIXTURE_OR_CACHE = "fixture/cache"


class DatabaseError(RuntimeError):
    """Raised when SQLite persistence or caching fails safely."""


@dataclass(frozen=True, slots=True)
class StoredSeriesMetadata:
    """Stored metadata for one supported series."""

    series_id: str
    display_name: str
    units: str
    frequency: str
    updated_at_utc: str


@dataclass(frozen=True, slots=True)
class ValidatedObservation:
    """Validated FRED observation ready for SQLite storage."""

    date: str
    value: str


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    """Observation loaded from SQLite."""

    series_id: str
    observation_date: date
    value: str
    is_missing: bool
    numeric_value: Decimal | None


@dataclass(frozen=True, slots=True)
class FetchRunRecord:
    """Metadata describing one fetch run."""

    series_id: str
    requested_start_date: date | None
    requested_end_date: date | None
    fetched_at_utc: datetime
    validated_observation_count: int
    source_kind: str


def initialize_schema(db_path: Path | str = DEFAULT_DATABASE_PATH) -> Path:
    """Create the database directory, schema, and supported-series catalog."""

    path = _normalize_db_path(db_path)
    _ensure_parent_directory(path)

    try:
        with _connect(path) as connection:
            _create_schema(connection)
            _upsert_supported_series_metadata(connection, SUPPORTED_SERIES)
    except (sqlite3.Error, OSError) as exc:
        raise DatabaseError(f"Could not initialize SQLite database at {path}.") from exc

    return path


def save_supported_series_metadata(
    db_or_connection: Path | str | sqlite3.Connection,
    series: Sequence[SupportedSeries] = SUPPORTED_SERIES,
) -> None:
    """Upsert supported-series metadata from the central catalog."""

    def _save(connection: sqlite3.Connection) -> None:
        _upsert_supported_series_metadata(connection, series)

    _execute_write(db_or_connection, _save)


def upsert_validated_observations(
    db_or_connection: Path | str | sqlite3.Connection,
    *,
    series_id: str,
    observations: Sequence[ValidatedObservation],
) -> None:
    """Insert or update validated observations for one supported series."""

    if not is_supported_series(series_id):
        raise DatabaseError(f"Unsupported series ID '{series_id}'.")

    def _save(connection: sqlite3.Connection) -> None:
        _upsert_validated_observations(connection, series_id=series_id, observations=observations)

    _execute_write(db_or_connection, _save)


def record_fetch_run(
    db_or_connection: Path | str | sqlite3.Connection,
    *,
    series_id: str,
    requested_start_date: date | None,
    requested_end_date: date | None,
    validated_observation_count: int,
    source_kind: str,
    fetched_at_utc: datetime | None = None,
) -> FetchRunRecord:
    """Persist one fetch run and return the recorded values."""

    if not is_supported_series(series_id):
        raise DatabaseError(f"Unsupported series ID '{series_id}'.")
    if source_kind not in {FETCH_SOURCE_LIVE, FETCH_SOURCE_FIXTURE_OR_CACHE}:
        raise DatabaseError(f"Unsupported fetch source '{source_kind}'.")
    if requested_start_date is not None and requested_end_date is not None:
        if requested_start_date > requested_end_date:
            raise ValueError("requested_start_date cannot be after requested_end_date")

    timestamp = fetched_at_utc or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)

    def _save(connection: sqlite3.Connection) -> None:
        _insert_fetch_run(
            connection,
            series_id=series_id,
            requested_start_date=requested_start_date,
            requested_end_date=requested_end_date,
            validated_observation_count=validated_observation_count,
            source_kind=source_kind,
            fetched_at_utc=timestamp,
        )

    _execute_write(db_or_connection, _save)
    return FetchRunRecord(
        series_id=series_id,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        fetched_at_utc=timestamp,
        validated_observation_count=validated_observation_count,
        source_kind=source_kind,
    )


def read_observations(
    db_path: Path | str = DEFAULT_DATABASE_PATH,
    *,
    series_id: str,
    observation_start: date | str | None = None,
    observation_end: date | str | None = None,
) -> tuple[ObservationRecord, ...]:
    """Read one series over an optional date range."""

    _validate_requested_series_and_dates(series_id, observation_start, observation_end)
    start_text, end_text = _range_to_text(observation_start, observation_end)

    try:
        with _connect(_normalize_db_path(db_path)) as connection:
            rows = connection.execute(
                """
                SELECT series_id, observation_date, value_text, is_missing, numeric_value_text
                FROM validated_observations
                WHERE series_id = ?
                  AND (? IS NULL OR observation_date >= ?)
                  AND (? IS NULL OR observation_date <= ?)
                ORDER BY observation_date ASC
                """,
                (series_id, start_text, start_text, end_text, end_text),
            ).fetchall()
    except sqlite3.Error as exc:
        raise DatabaseError("Could not read observations from SQLite.") from exc

    return tuple(_row_to_observation_record(row) for row in rows)


def read_multiple_observations(
    db_path: Path | str = DEFAULT_DATABASE_PATH,
    *,
    series_ids: Sequence[str],
    observation_start: date | str | None = None,
    observation_end: date | str | None = None,
) -> dict[str, tuple[ObservationRecord, ...]]:
    """Read multiple series over an optional date range."""

    if not series_ids:
        return {}
    for series_id in series_ids:
        if not is_supported_series(series_id):
            raise DatabaseError(f"Unsupported series ID '{series_id}'.")
    start_text, end_text = _range_to_text(observation_start, observation_end)
    placeholders = ", ".join("?" for _ in series_ids)

    try:
        with _connect(_normalize_db_path(db_path)) as connection:
            rows = connection.execute(
                f"""
                SELECT series_id, observation_date, value_text, is_missing, numeric_value_text
                FROM validated_observations
                WHERE series_id IN ({placeholders})
                  AND (? IS NULL OR observation_date >= ?)
                  AND (? IS NULL OR observation_date <= ?)
                ORDER BY series_id ASC, observation_date ASC
                """,
                (*series_ids, start_text, start_text, end_text, end_text),
            ).fetchall()
    except sqlite3.Error as exc:
        raise DatabaseError("Could not read multiple series from SQLite.") from exc

    grouped: dict[str, list[ObservationRecord]] = {series_id: [] for series_id in series_ids}
    for row in rows:
        record = _row_to_observation_record(row)
        grouped[record.series_id].append(record)
    return {series_id: tuple(grouped[series_id]) for series_id in series_ids}


def cached_observations_exist(
    db_path: Path | str = DEFAULT_DATABASE_PATH,
    *,
    series_id: str,
    observation_start: date | str | None = None,
    observation_end: date | str | None = None,
) -> bool:
    """Return whether any cached observations exist for a requested range."""

    _validate_requested_series_and_dates(series_id, observation_start, observation_end)
    start_text, end_text = _range_to_text(observation_start, observation_end)

    try:
        with _connect(_normalize_db_path(db_path)) as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM validated_observations
                WHERE series_id = ?
                  AND (? IS NULL OR observation_date >= ?)
                  AND (? IS NULL OR observation_date <= ?)
                LIMIT 1
                """,
                (series_id, start_text, start_text, end_text, end_text),
            ).fetchone()
    except sqlite3.Error as exc:
        raise DatabaseError("Could not inspect cached observations in SQLite.") from exc

    return row is not None


def get_latest_fetch_information(
    db_path: Path | str = DEFAULT_DATABASE_PATH,
    *,
    series_id: str | None = None,
) -> FetchRunRecord | None:
    """Return the newest recorded fetch run, optionally scoped to one series."""

    if series_id is not None and not is_supported_series(series_id):
        raise DatabaseError(f"Unsupported series ID '{series_id}'.")

    try:
        with _connect(_normalize_db_path(db_path)) as connection:
            if series_id is None:
                row = connection.execute(
                    """
                    SELECT series_id, requested_start_date, requested_end_date, fetched_at_utc,
                           validated_observation_count, source_kind
                    FROM fetch_runs
                    ORDER BY fetched_at_utc DESC, fetch_run_id DESC
                    LIMIT 1
                    """
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT series_id, requested_start_date, requested_end_date, fetched_at_utc,
                           validated_observation_count, source_kind
                    FROM fetch_runs
                    WHERE series_id = ?
                    ORDER BY fetched_at_utc DESC, fetch_run_id DESC
                    LIMIT 1
                    """,
                    (series_id,),
                ).fetchone()
    except sqlite3.Error as exc:
        raise DatabaseError("Could not read latest fetch information from SQLite.") from exc

    if row is None:
        return None

    return FetchRunRecord(
        series_id=row[0],
        requested_start_date=_text_to_date(row[1]),
        requested_end_date=_text_to_date(row[2]),
        fetched_at_utc=datetime.fromisoformat(row[3]),
        validated_observation_count=row[4],
        source_kind=row[5],
    )


def store_validated_monitor_data(
    db_path: Path | str,
    *,
    series_id: str,
    observations: Sequence[ValidatedObservation],
    requested_start_date: date | None,
    requested_end_date: date | None,
    source_kind: str,
) -> FetchRunRecord:
    """Store validated observations and record the fetch run that produced them."""

    path = initialize_schema(db_path)
    with _connect(path) as connection:
        try:
            _create_schema(connection)
            _upsert_supported_series_metadata(connection, SUPPORTED_SERIES)
            _upsert_validated_observations(
                connection,
                series_id=series_id,
                observations=observations,
            )
            record = _insert_fetch_run(
                connection,
                series_id=series_id,
                requested_start_date=requested_start_date,
                requested_end_date=requested_end_date,
                validated_observation_count=len(observations),
                source_kind=source_kind,
                fetched_at_utc=None,
            )
        except (sqlite3.Error, DatabaseError, ValueError) as exc:
            raise DatabaseError("Could not store validated monitoring data.") from exc
    return record


@contextmanager
def _connect(path: Path):
    _ensure_parent_directory(path)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS supported_series (
            series_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            units TEXT NOT NULL,
            frequency TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS validated_observations (
            series_id TEXT NOT NULL,
            observation_date TEXT NOT NULL,
            value_text TEXT NOT NULL,
            is_missing INTEGER NOT NULL CHECK (is_missing IN (0, 1)),
            numeric_value_text TEXT,
            validated_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL,
            PRIMARY KEY (series_id, observation_date),
            FOREIGN KEY (series_id) REFERENCES supported_series(series_id)
                ON UPDATE CASCADE
                ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS fetch_runs (
            fetch_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id TEXT NOT NULL,
            requested_start_date TEXT,
            requested_end_date TEXT,
            fetched_at_utc TEXT NOT NULL,
            validated_observation_count INTEGER NOT NULL CHECK (validated_observation_count >= 0),
            source_kind TEXT NOT NULL,
            FOREIGN KEY (series_id) REFERENCES supported_series(series_id)
                ON UPDATE CASCADE
                ON DELETE RESTRICT
        );

        CREATE INDEX IF NOT EXISTS idx_validated_observations_series_date
            ON validated_observations(series_id, observation_date);

        CREATE INDEX IF NOT EXISTS idx_fetch_runs_series_timestamp
            ON fetch_runs(series_id, fetched_at_utc DESC, fetch_run_id DESC);
        """
    )


def _upsert_supported_series_metadata(
    connection: sqlite3.Connection,
    series: Sequence[SupportedSeries],
) -> None:
    timestamp = _utc_now()
    connection.executemany(
        """
        INSERT INTO supported_series (
            series_id, display_name, units, frequency, updated_at_utc
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(series_id) DO UPDATE SET
            display_name = excluded.display_name,
            units = excluded.units,
            frequency = excluded.frequency,
            updated_at_utc = excluded.updated_at_utc
        """,
        [
            (
                item.series_id,
                item.display_name,
                item.units,
                item.frequency,
                timestamp,
            )
            for item in series
        ],
    )


def _upsert_validated_observations(
    connection: sqlite3.Connection,
    *,
    series_id: str,
    observations: Sequence[ValidatedObservation],
) -> None:
    timestamp = _utc_now()
    connection.executemany(
        """
        INSERT INTO validated_observations (
            series_id,
            observation_date,
            value_text,
            is_missing,
            numeric_value_text,
            validated_at_utc,
            updated_at_utc
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(series_id, observation_date) DO UPDATE SET
            value_text = excluded.value_text,
            is_missing = excluded.is_missing,
            numeric_value_text = excluded.numeric_value_text,
            validated_at_utc = excluded.validated_at_utc,
            updated_at_utc = excluded.updated_at_utc
        """,
        [
            (
                series_id,
                observation.date,
                observation.value,
                1 if observation.value == "." else 0,
                None if observation.value == "." else observation.value,
                timestamp,
                timestamp,
            )
            for observation in observations
        ],
    )


def _insert_fetch_run(
    connection: sqlite3.Connection,
    *,
    series_id: str,
    requested_start_date: date | None,
    requested_end_date: date | None,
    validated_observation_count: int,
    source_kind: str,
    fetched_at_utc: datetime | None,
) -> FetchRunRecord:
    timestamp = fetched_at_utc or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    connection.execute(
        """
        INSERT INTO fetch_runs (
            series_id,
            requested_start_date,
            requested_end_date,
            fetched_at_utc,
            validated_observation_count,
            source_kind
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            series_id,
            _date_to_text(requested_start_date),
            _date_to_text(requested_end_date),
            timestamp.isoformat(),
            validated_observation_count,
            source_kind,
        ),
    )
    return FetchRunRecord(
        series_id=series_id,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        fetched_at_utc=timestamp,
        validated_observation_count=validated_observation_count,
        source_kind=source_kind,
    )


def _execute_write(
    db_or_connection: Path | str | sqlite3.Connection,
    callback: Callable[[sqlite3.Connection], None],
) -> None:
    try:
        if isinstance(db_or_connection, sqlite3.Connection):
            callback(db_or_connection)
            return
        path = _normalize_db_path(db_or_connection)
        _ensure_parent_directory(path)
        with _connect(path) as connection:
            _create_schema(connection)
            callback(connection)
    except (sqlite3.Error, OSError) as exc:
        raise DatabaseError("Could not update SQLite database.") from exc


def _row_to_observation_record(row: sqlite3.Row | tuple[str, str, str, int, str | None]) -> ObservationRecord:
    numeric_value = None
    if row[4] is not None:
        try:
            numeric_value = Decimal(row[4])
        except InvalidOperation as exc:
            raise DatabaseError("Stored numeric observation value is invalid.") from exc

    return ObservationRecord(
        series_id=row[0],
        observation_date=date.fromisoformat(row[1]),
        value=row[2],
        is_missing=bool(row[3]),
        numeric_value=numeric_value,
    )


def _normalize_db_path(db_path: Path | str) -> Path:
    path = Path(db_path).expanduser()
    if path.exists() and path.is_dir():
        raise DatabaseError(f"Database path {path} is a directory.")
    return path


def _ensure_parent_directory(path: Path) -> None:
    parent = path.parent
    if parent != Path("."):
        parent.mkdir(parents=True, exist_ok=True)


def _range_to_text(
    observation_start: date | str | None,
    observation_end: date | str | None,
) -> tuple[str | None, str | None]:
    start = _coerce_date(observation_start)
    end = _coerce_date(observation_end)
    if start is not None and end is not None and start > end:
        raise ValueError("observation_start cannot be after observation_end")
    return _date_to_text(start), _date_to_text(end)


def _validate_requested_series_and_dates(
    series_id: str,
    observation_start: date | str | None,
    observation_end: date | str | None,
) -> None:
    if not is_supported_series(series_id):
        raise DatabaseError(f"Unsupported series ID '{series_id}'.")
    _range_to_text(observation_start, observation_end)


def _coerce_date(value: date | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _date_to_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _text_to_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value is not None else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
