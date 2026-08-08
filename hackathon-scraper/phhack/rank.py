"""Scoring. Prize size dominates, by design.

The score is a 0-100 blend of three signals:

  prize (62%)      log-scaled PHP value of the pot
  relevance (23%)  how reachable the event is from the Philippines
  urgency (15%)    a deadline close enough to act on, but not already past

Log scaling matters: on a linear scale a single ₱50M crypto bounty would flatten
every local event to ~0. Log keeps a ₱500K Manila hackathon meaningfully ranked
against a ₱5M global one while still putting the bigger pot on top.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Iterable, List, Optional

from .geo import PH_TIER_GLOBAL, PH_TIER_LOCAL, PH_TIER_NONE, PH_TIER_SEASIA
from .models import STATUS_ENDED, Hackathon

WEIGHT_PRIZE = 0.62
WEIGHT_RELEVANCE = 0.23
WEIGHT_URGENCY = 0.15

#: Pot at which the prize component saturates. Above this, bigger stops helping.
PRIZE_CAP_PHP = 5_000_000.0

#: Listings with no prize figure should not outrank a known modest prize, but
#: should not be buried either — plenty of good events publish prizes late.
UNKNOWN_PRIZE_COMPONENT = 0.15

TIER_WEIGHTS = {
    PH_TIER_LOCAL: 1.00,
    PH_TIER_SEASIA: 0.80,
    PH_TIER_GLOBAL: 0.55,
    PH_TIER_NONE: 0.00,
}

#: Sweet spot for acting on a deadline: far enough to build, close enough to matter.
URGENCY_IDEAL_DAYS = 30
URGENCY_HORIZON_DAYS = 120


def prize_component(prize_php: Optional[float]) -> float:
    if prize_php is None:
        return UNKNOWN_PRIZE_COMPONENT
    if prize_php <= 0:
        return 0.0
    return min(1.0, math.log10(1.0 + prize_php) / math.log10(1.0 + PRIZE_CAP_PHP))


def relevance_component(tier: str) -> float:
    return TIER_WEIGHTS.get(tier, 0.0)


def urgency_component(hackathon: Hackathon, today: Optional[date] = None) -> float:
    """Peaks around a month out, decays either side, zero once it has closed."""
    if hackathon.status == STATUS_ENDED:
        return 0.0

    reference = hackathon.ends_on or hackathon.starts_on
    if reference is None:
        return 0.3  # No dates: neutral-ish rather than penalised.

    today = today or date.today()
    days_left = (reference - today).days

    if days_left < 0:
        return 0.0
    if days_left <= URGENCY_IDEAL_DAYS:
        # Very close deadlines are slightly discounted — hard to prepare for.
        return 0.6 + 0.4 * (days_left / URGENCY_IDEAL_DAYS)
    if days_left >= URGENCY_HORIZON_DAYS:
        return 0.2
    span = URGENCY_HORIZON_DAYS - URGENCY_IDEAL_DAYS
    return 1.0 - 0.8 * ((days_left - URGENCY_IDEAL_DAYS) / span)


def score(hackathon: Hackathon, today: Optional[date] = None) -> float:
    blended = (
        WEIGHT_PRIZE * prize_component(hackathon.prize_php)
        + WEIGHT_RELEVANCE * relevance_component(hackathon.ph_tier)
        + WEIGHT_URGENCY * urgency_component(hackathon, today)
    )
    return round(blended * 100.0, 1)


def apply_scores(
    hackathons: Iterable[Hackathon], today: Optional[date] = None
) -> List[Hackathon]:
    items = list(hackathons)
    for item in items:
        item.score = score(item, today)
    return items


def sort_key(mode: str):
    """Sort keys for the `--sort` modes. All sort descending by relevance."""
    if mode == "prize":
        # Unknown prizes sink, but ties break on score so they stay ordered.
        return lambda h: (h.prize_php if h.prize_php is not None else -1.0, h.score)
    if mode == "deadline":
        # Soonest first, so negate for the shared reverse=True sort.
        far_future = date(9999, 12, 31)
        return lambda h: (
            -((h.ends_on or h.starts_on or far_future) - date(1970, 1, 1)).days,
            h.score,
        )
    if mode == "score":
        return lambda h: (h.score, h.prize_php or 0.0)
    raise ValueError(f"unknown sort mode: {mode}")


def sort_hackathons(hackathons: Iterable[Hackathon], mode: str = "prize") -> List[Hackathon]:
    return sorted(hackathons, key=sort_key(mode), reverse=True)
