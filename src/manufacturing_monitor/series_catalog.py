from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SupportedSeries:
    series_id: str
    display_name: str
    units: str
    frequency: str


SUPPORTED_SERIES: tuple[SupportedSeries, ...] = (
    SupportedSeries(
        series_id="IPMAN",
        display_name="Industrial Production: Manufacturing (NAICS)",
        units="Index 2017=100, Seasonally Adjusted",
        frequency="Monthly",
    ),
    SupportedSeries(
        series_id="IPDMAN",
        display_name="Industrial Production: Durable Manufacturing (NAICS)",
        units="Index 2017=100, Seasonally Adjusted",
        frequency="Monthly",
    ),
    SupportedSeries(
        series_id="IPNMAN",
        display_name="Industrial Production: Nondurable Manufacturing (NAICS)",
        units="Index 2017=100, Seasonally Adjusted",
        frequency="Monthly",
    ),
    SupportedSeries(
        series_id="MCUMFN",
        display_name="Capacity Utilization: Manufacturing (NAICS)",
        units="Percent, Seasonally Adjusted",
        frequency="Monthly",
    ),
    SupportedSeries(
        series_id="PCUOMFGOMFG",
        display_name="Producer Price Index by Industry: Total Manufacturing Industries",
        units="Index Dec 1984=100, Not Seasonally Adjusted",
        frequency="Monthly",
    ),
)

SUPPORTED_SERIES_BY_ID: dict[str, SupportedSeries] = {
    series.series_id: series for series in SUPPORTED_SERIES
}


def get_supported_series(series_id: str) -> SupportedSeries:
    try:
        return SUPPORTED_SERIES_BY_ID[series_id]
    except KeyError as exc:
        raise KeyError(series_id) from exc


def is_supported_series(series_id: str) -> bool:
    return series_id in SUPPORTED_SERIES_BY_ID


def supported_series_ids() -> tuple[str, ...]:
    return tuple(series.series_id for series in SUPPORTED_SERIES)
