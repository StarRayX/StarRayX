"""Renderers: plain table, JSON, CSV, Markdown. No third-party dependencies."""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from typing import List, Optional, Sequence

from .models import Hackathon
from .money import format_php

FORMATS = ("table", "json", "csv", "md")

_TIER_BADGE = {
    "local": "PH",
    "seasia": "SEA",
    "global": "GLOBAL",
    "none": "-",
}


def _dates(item: Hackathon) -> str:
    if item.starts_on and item.ends_on:
        return f"{item.starts_on:%d %b} – {item.ends_on:%d %b %Y}"
    if item.ends_on:
        return f"ends {item.ends_on:%d %b %Y}"
    if item.starts_on:
        return f"from {item.starts_on:%d %b %Y}"
    return item.deadline_text or "—"


def _days_left(item: Hackathon, today: Optional[date] = None) -> str:
    reference = item.ends_on or item.starts_on
    if reference is None:
        return "—"
    delta = (reference - (today or date.today())).days
    if delta < 0:
        return "closed"
    return f"{delta}d"


def _truncate(text: str, width: int) -> str:
    text = text or ""
    return text if len(text) <= width else text[: width - 1] + "…"


def render_table(items: Sequence[Hackathon], today: Optional[date] = None) -> str:
    """Fixed-width table sized for an 80-120 column terminal."""
    if not items:
        return "No hackathons matched the current filters."

    headers = ["#", "PRIZE", "SCORE", "TIER", "LEFT", "TITLE", "SOURCE"]
    rows: List[List[str]] = []
    for index, item in enumerate(items, start=1):
        rows.append(
            [
                str(index),
                format_php(item.prize_php),
                f"{item.score:.0f}",
                _TIER_BADGE.get(item.ph_tier, item.ph_tier),
                _days_left(item, today),
                _truncate(item.title, 46),
                item.source,
            ]
        )

    widths = [
        max(len(headers[col]), max(len(row[col]) for row in rows))
        for col in range(len(headers))
    ]

    def line(cells: Sequence[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells)).rstrip()

    out = [line(headers), "  ".join("-" * w for w in widths)]
    for row, item in zip(rows, items):
        out.append(line(row))
        out.append(f"     {item.url}")
    return "\n".join(out)


def render_json(items: Sequence[Hackathon], today: Optional[date] = None) -> str:
    payload = {
        "generated_on": (today or date.today()).isoformat(),
        "count": len(items),
        "hackathons": [item.to_dict() for item in items],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


CSV_COLUMNS = (
    "score", "prize_php", "prize_amount", "prize_currency", "ph_tier",
    "title", "url", "source", "organizer", "location_text", "is_online",
    "starts_on", "ends_on", "status", "participants", "themes",
    "ph_reason", "also_seen_on",
)


def render_csv(items: Sequence[Hackathon], today: Optional[date] = None) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS), extrasaction="ignore")
    writer.writeheader()
    for item in items:
        row = item.to_dict()
        row["themes"] = "; ".join(item.themes)
        row["also_seen_on"] = "; ".join(item.also_seen_on)
        writer.writerow(row)
    return buffer.getvalue()


def render_markdown(items: Sequence[Hackathon], today: Optional[date] = None) -> str:
    stamp = (today or date.today()).isoformat()
    if not items:
        return f"# Philippine hackathon watch\n\n_Updated {stamp}_\n\nNo hackathons matched the current filters.\n"

    lines = [
        "# Philippine hackathon watch",
        "",
        f"_Updated {stamp} · {len(items)} listing(s), highest prize pools first_",
        "",
        "| # | Prize (PHP) | Score | Scope | Closes | Hackathon | Source |",
        "|---:|---:|---:|:--|:--|:--|:--|",
    ]
    for index, item in enumerate(items, start=1):
        title = item.title.replace("|", "\\|")
        lines.append(
            "| {i} | {prize} | {score:.0f} | {tier} | {left} | [{title}]({url}) | {source} |".format(
                i=index,
                prize=format_php(item.prize_php),
                score=item.score,
                tier=_TIER_BADGE.get(item.ph_tier, item.ph_tier),
                left=_dates(item),
                title=title,
                url=item.url,
                source=item.source,
            )
        )
    lines.append("")
    return "\n".join(lines)


def render(fmt: str, items: Sequence[Hackathon], today: Optional[date] = None) -> str:
    if fmt == "table":
        return render_table(items, today)
    if fmt == "json":
        return render_json(items, today)
    if fmt == "csv":
        return render_csv(items, today)
    if fmt == "md":
        return render_markdown(items, today)
    raise ValueError(f"unknown format '{fmt}' (choose from {', '.join(FORMATS)})")
