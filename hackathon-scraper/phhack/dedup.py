"""Cross-source de-duplication.

The same hackathon is routinely listed on Devpost and Devfolio and Unstop. Left
alone it occupies three rows near the top of a prize-sorted list, which is
exactly where the noise hurts most.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse

from .geo import tier_rank
from .models import Hackathon

# Words that carry no identity: every listing has them.
_NOISE_WORDS = {
    "hackathon", "hack", "challenge", "competition", "contest", "the", "a", "an",
    "online", "global", "international", "national", "official", "season",
    "edition", "series", "event", "buildathon", "codefest", "datathon", "jam",
}

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")


def title_key(title: str) -> str:
    """Reduce a title to its identifying words.

    "TECHATHLON 2026 Hackathon" and "Techathlon Hackathon (2026)" both collapse
    to "techathlon".
    """
    text = (title or "").lower()
    text = _YEAR_RE.sub(" ", text)
    text = _NON_ALNUM_RE.sub(" ", text)
    words = [w for w in text.split() if w and w not in _NOISE_WORDS]
    if not words:
        # Title was nothing but noise words; fall back to the raw form so
        # unrelated listings do not all collapse onto an empty key.
        return " ".join((title or "").lower().split())
    return " ".join(sorted(set(words)))


def url_key(url: str) -> str:
    """Host-based identity, ignoring the `www.` prefix and the path."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _better(current: Hackathon, candidate: Hackathon) -> bool:
    """Prefer the richer record: known prize, then PH relevance, then detail."""
    if (candidate.prize_php or 0) != (current.prize_php or 0):
        return (candidate.prize_php or 0) > (current.prize_php or 0)
    if tier_rank(candidate.ph_tier) != tier_rank(current.ph_tier):
        return tier_rank(candidate.ph_tier) < tier_rank(current.ph_tier)

    def detail(item: Hackathon) -> int:
        return sum(
            1
            for field in (
                item.starts_on, item.ends_on, item.organizer,
                item.location_text, item.participants,
            )
            if field
        )

    return detail(candidate) > detail(current)


def dedupe(hackathons: Iterable[Hackathon]) -> List[Hackathon]:
    """Merge duplicates, keeping the richest record and noting the others.

    Two listings match on identical title keys, or on a shared host for
    dedicated event domains. The host rule deliberately skips shared platform
    domains, where every unrelated event lives under one hostname.
    """
    shared_hosts = {
        "devpost.com", "devfolio.co", "unstop.com",
        "dorahacks.io", "hackerearth.com", "mlh.io",
    }

    by_title: Dict[str, Hackathon] = {}
    by_host: Dict[str, Hackathon] = {}
    order: List[Hackathon] = []
    position: Dict[int, int] = {}

    for item in hackathons:
        tkey = title_key(item.title)
        hkey = url_key(item.url)
        host_usable = bool(hkey) and hkey not in shared_hosts

        existing: Optional[Hackathon] = by_title.get(tkey)
        if existing is None and host_usable:
            existing = by_host.get(hkey)

        if existing is None:
            by_title[tkey] = item
            if host_usable:
                by_host[hkey] = item
            position[id(item)] = len(order)
            order.append(item)
            continue

        if _better(existing, item):
            # Swap in the richer record, preserving list position and history.
            inherited = set(existing.also_seen_on) | {existing.source}
            item.also_seen_on = sorted(inherited - {item.source})
            slot = position.pop(id(existing))
            order[slot] = item
            position[id(item)] = slot
            by_title[tkey] = item
            if host_usable:
                by_host[hkey] = item
        elif item.source != existing.source:
            existing.also_seen_on = sorted(set(existing.also_seen_on) | {item.source})

    return order
