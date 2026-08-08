"""Orchestration: fetch -> enrich -> filter -> dedupe -> score -> sort."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence, Set

from . import geo, rank
from .dedup import dedupe
from .models import STATUS_UNKNOWN, Hackathon
from .money import DEFAULT_RATES_PHP, parse_prize
from .sources import FetchContext, Source, default_currency_for

log = logging.getLogger(__name__)


@dataclass
class RunReport:
    """What each source contributed, and how it failed if it did."""

    fetched: Dict[str, int] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)
    total_raw: int = 0
    after_filter: int = 0
    after_dedupe: int = 0

    def add_error(self, source: str, message: str) -> None:
        self.errors[source] = message


def collect(
    sources: Sequence[Source],
    ctx: FetchContext,
    strict: bool = False,
    report: Optional[RunReport] = None,
) -> List[Hackathon]:
    """Fetch from every source.

    One source failing must never lose the results of the others — a drifted
    schema on an experimental adapter should cost a warning, not the run. Pass
    `strict=True` to make failures fatal instead.
    """
    report = report or RunReport()
    collected: List[Hackathon] = []

    for source in sources:
        try:
            items = list(source.fetch(ctx))
        except Exception as exc:  # noqa: BLE001 - adapters touch the open internet
            message = f"{type(exc).__name__}: {exc}"
            log.warning("source '%s' failed: %s", source.name, message)
            report.add_error(source.name, message)
            if strict:
                raise
            continue

        report.fetched[source.name] = len(items)
        collected.extend(items)
        log.info("source '%s' returned %d listing(s)", source.name, len(items))

    report.total_raw = len(collected)
    return collected


def enrich(
    hackathons: Sequence[Hackathon],
    rates: Optional[Dict[str, float]] = None,
) -> List[Hackathon]:
    """Parse prizes into PHP and classify Philippine relevance."""
    rates = rates or DEFAULT_RATES_PHP

    for item in hackathons:
        money = parse_prize(item.prize_text, default_currency_for(item.source))
        if money is not None:
            item.prize_amount = money.amount
            item.prize_currency = money.currency
            item.prize_php = money.to_php(rates)

        tier, reason = geo.classify(
            item.searchable_text(), is_online=bool(item.is_online)
        )
        item.ph_tier = tier
        item.ph_reason = reason

    return list(hackathons)


def filter_listings(
    hackathons: Sequence[Hackathon],
    tiers: Set[str],
    statuses: Optional[Set[str]] = None,
    min_prize_php: float = 0.0,
    require_prize: bool = False,
) -> List[Hackathon]:
    """Apply the user's filters.

    A listing with no prize figure survives `min_prize_php` unless
    `require_prize` is set, because "prize not published yet" is common and is
    not the same as "prize too small".
    """
    out: List[Hackathon] = []
    for item in hackathons:
        if item.ph_tier not in tiers:
            continue
        # An unknown status is kept: several sources simply do not report one,
        # and dropping those would silently hide real events.
        if statuses and item.status not in statuses and item.status != STATUS_UNKNOWN:
            continue
        if item.prize_php is None:
            if require_prize:
                continue
        elif item.prize_php < min_prize_php:
            continue
        out.append(item)
    return out


def run(
    sources: Sequence[Source],
    ctx: FetchContext,
    tiers: Set[str],
    statuses: Optional[Set[str]] = None,
    min_prize_php: float = 0.0,
    require_prize: bool = False,
    sort_mode: str = "prize",
    limit: Optional[int] = None,
    rates: Optional[Dict[str, float]] = None,
    strict: bool = False,
    today: Optional[date] = None,
) -> tuple[List[Hackathon], RunReport]:
    report = RunReport()

    raw = collect(sources, ctx, strict=strict, report=report)
    enriched = enrich(raw, rates=rates)

    filtered = filter_listings(
        enriched,
        tiers=tiers,
        statuses=statuses,
        min_prize_php=min_prize_php,
        require_prize=require_prize,
    )
    report.after_filter = len(filtered)

    # Scored before de-duplication so the merge can compare like with like.
    rank.apply_scores(filtered, today=today)
    merged = dedupe(filtered)
    report.after_dedupe = len(merged)

    ordered = rank.sort_hackathons(merged, mode=sort_mode)
    if limit is not None and limit > 0:
        ordered = ordered[:limit]
    return ordered, report
