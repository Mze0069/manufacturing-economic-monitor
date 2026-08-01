"""Generate reproducible evidence used by the Practicum 6 Quarto report.

The script loads cached observations through the project's existing analytics
layer, writes a Markdown summary table, and creates a normalized SVG chart.
It does not contact FRED and does not require an API key.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import Iterable

from manufacturing_monitor.analytics import MultiSeriesResult, SeriesObservationRow, process_multiple_series


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "manufacturing_monitor.db"
GENERATED_DIR = Path(__file__).resolve().parent / "generated"
START_DATE = date(2017, 1, 1)
SERIES_IDS = ("IPMAN", "IPDMAN", "IPNMAN", "MCUMFN", "PCUOMFGOMFG")

COLORS = {
    "IPMAN": "#2563eb",
    "IPDMAN": "#0f766e",
    "IPNMAN": "#dc2626",
    "MCUMFN": "#7c3aed",
    "PCUOMFGOMFG": "#d97706",
}


def latest_valid_rows(result: MultiSeriesResult) -> list[SeriesObservationRow]:
    """Return the latest nonmissing normalized row for each requested series."""

    grouped: dict[str, list[SeriesObservationRow]] = defaultdict(list)
    for row in result.normalized_rows:
        if not row.is_missing and row.normalized_value is not None:
            grouped[row.series_id].append(row)

    latest: list[SeriesObservationRow] = []
    for series_id in result.requested_series_ids:
        rows = grouped.get(series_id, [])
        if rows:
            latest.append(max(rows, key=lambda item: item.date))
    return latest


def write_summary_markdown(result: MultiSeriesResult, path: Path) -> None:
    """Write the report question, generated table, and concise interpretation."""

    rows = latest_valid_rows(result)
    if not rows:
        raise RuntimeError("No valid normalized observations were available for the report.")

    farthest = max(
        rows,
        key=lambda row: abs((row.normalized_value or Decimal("100")) - Decimal("100")),
    )
    change = (farthest.normalized_value or Decimal("100")) - Decimal("100")

    lines = [
        "## Generated answer",
        "",
        (
            f"**Answer:** `{farthest.series_id}` moved farthest from its "
            f"January 2017 baseline. Its latest normalized index is "
            f"**{farthest.normalized_value:.2f}**, a change of **{change:+.2f}%** "
            f"from the baseline value of 100."
        ),
        "",
        "| Series | Latest date | Latest raw value | Units | Normalized index | Change from baseline |",
        "|---|---:|---:|---|---:|---:|",
    ]

    summary_by_id = {
        item.summary.series_id: item.summary for item in result.series_results
    }
    for row in sorted(rows, key=lambda item: item.series_id):
        summary = summary_by_id[row.series_id]
        normalized = row.normalized_value or Decimal("100")
        lines.append(
            "| "
            f"`{row.series_id}` | {row.date.isoformat()} | {row.raw_value} | "
            f"{summary.units} | {normalized:.2f} | {normalized - Decimal('100'):+.2f}% |"
        )

    lines.extend(
        [
            "",
            "The normalized measure answers a relative-change question without mixing "
            "the original units. The raw values remain available in the table for "
            "context, but direct comparisons across incompatible units should be avoided.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _scale(value: Decimal, minimum: Decimal, maximum: Decimal, start: float, end: float) -> float:
    """Map a decimal value linearly into a drawing interval."""

    if maximum == minimum:
        return (start + end) / 2
    ratio = float((value - minimum) / (maximum - minimum))
    return start + ratio * (end - start)


def write_normalized_svg(rows: Iterable[SeriesObservationRow], path: Path) -> None:
    """Create a dependency-free SVG line chart from normalized project rows."""

    grouped: dict[str, list[SeriesObservationRow]] = defaultdict(list)
    for row in rows:
        if row.normalized_value is not None and not row.is_missing:
            grouped[row.series_id].append(row)

    all_rows = [row for series_rows in grouped.values() for row in series_rows]
    if not all_rows:
        raise RuntimeError("No normalized rows were available for the report figure.")

    for series_rows in grouped.values():
        series_rows.sort(key=lambda item: item.date)

    width, height = 920, 520
    left, right, top, bottom = 85, 220, 55, 70
    plot_width = width - left - right
    plot_height = height - top - bottom

    dates = [row.date for row in all_rows]
    values = [row.normalized_value for row in all_rows if row.normalized_value is not None]
    min_date, max_date = min(dates), max(dates)
    min_value = min(values) - Decimal("5")
    max_value = max(values) + Decimal("5")

    date_min = Decimal(min_date.toordinal())
    date_max = Decimal(max_date.toordinal())

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="20" y="28" font-family="Arial" font-size="20" font-weight="bold">Normalized manufacturing indicators (January 2017 = 100)</text>',
    ]

    # Horizontal grid and y labels.
    for index in range(6):
        value = min_value + (max_value - min_value) * Decimal(index) / Decimal(5)
        y = top + plot_height - (plot_height * index / 5)
        svg.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" stroke="#d1d5db" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" font-family="Arial" font-size="12">{value:.0f}</text>'
        )

    # Year labels.
    for year in range(min_date.year, max_date.year + 1):
        tick_date = date(year, 1, 1)
        if tick_date < min_date or tick_date > max_date:
            continue
        x = _scale(Decimal(tick_date.toordinal()), date_min, date_max, left, left + plot_width)
        svg.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_height}" stroke="#e5e7eb" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="{x:.1f}" y="{top + plot_height + 24}" text-anchor="middle" font-family="Arial" font-size="12">{year}</text>'
        )

    svg.append(
        f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="#111827" stroke-width="1.5"/>'
    )
    svg.append(
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#111827" stroke-width="1.5"/>'
    )

    for series_id in SERIES_IDS:
        series_rows = grouped.get(series_id, [])
        if not series_rows:
            continue
        points = []
        for row in series_rows:
            assert row.normalized_value is not None
            x = _scale(Decimal(row.date.toordinal()), date_min, date_max, left, left + plot_width)
            y = _scale(row.normalized_value, min_value, max_value, top + plot_height, top)
            points.append(f"{x:.1f},{y:.1f}")
        color = COLORS[series_id]
        svg.append(
            f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="2.3" stroke-linejoin="round" stroke-linecap="round"/>'
        )

    legend_x = left + plot_width + 25
    legend_y = top + 20
    for index, series_id in enumerate(SERIES_IDS):
        y = legend_y + index * 34
        color = COLORS[series_id]
        svg.append(
            f'<line x1="{legend_x}" y1="{y}" x2="{legend_x + 28}" y2="{y}" stroke="{color}" stroke-width="3"/>'
        )
        svg.append(
            f'<text x="{legend_x + 36}" y="{y + 4}" font-family="Arial" font-size="13">{escape(series_id)}</text>'
        )

    svg.append(
        f'<text x="{left + plot_width / 2:.1f}" y="{height - 18}" text-anchor="middle" font-family="Arial" font-size="13">Observation date</text>'
    )
    svg.append(
        f'<text x="20" y="{top + plot_height / 2:.1f}" transform="rotate(-90 20 {top + plot_height / 2:.1f})" text-anchor="middle" font-family="Arial" font-size="13">Normalized index</text>'
    )
    svg.append("</svg>")

    path.write_text("\n".join(svg), encoding="utf-8")


def main() -> None:
    """Generate all report evidence from the committed SQLite database."""

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    result = process_multiple_series(
        DATABASE_PATH,
        series_ids=SERIES_IDS,
        observation_start=START_DATE,
    )
    if result.status not in {"ok", "partial"}:
        raise RuntimeError(result.reason or f"Unexpected analytics status: {result.status}")

    write_summary_markdown(result, GENERATED_DIR / "summary.md")
    write_normalized_svg(result.normalized_rows, GENERATED_DIR / "normalized_comparison.svg")

    print(f"Generated {GENERATED_DIR / 'summary.md'}")
    print(f"Generated {GENERATED_DIR / 'normalized_comparison.svg'}")


if __name__ == "__main__":
    main()
