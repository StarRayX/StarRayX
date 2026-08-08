"""Decide how relevant a listing is to a hacker based in the Philippines.

Four tiers, most to least relevant:

``local``   explicitly Philippine — a PH city, a PH university, "Filipino", etc.
``seasia``  regional events a PH team is eligible for (ASEAN, APAC, SEA).
``global``  worldwide/online events, joinable from Manila.
``none``    tied to somewhere else entirely; dropped by default.
"""

from __future__ import annotations

import re
from typing import Iterable, Tuple

PH_TIER_LOCAL = "local"
PH_TIER_SEASIA = "seasia"
PH_TIER_GLOBAL = "global"
PH_TIER_NONE = "none"

TIER_ORDER = (PH_TIER_LOCAL, PH_TIER_SEASIA, PH_TIER_GLOBAL, PH_TIER_NONE)

_PH_KEYWORDS = (
    "philippines",
    "philippine",
    "filipino",
    "filipina",
    "pilipinas",
    "pinoy",
    "ph hackathon",
)

_PH_CITIES = (
    "manila",
    "quezon city",
    "makati",
    "taguig",
    "bonifacio global city",
    "pasig",
    "mandaluyong",
    "paranaque",
    "parañaque",
    "las pinas",
    "muntinlupa",
    "caloocan",
    "marikina",
    "valenzuela",
    "pasay",
    "metro manila",
    "cebu",
    "mandaue",
    "lapu-lapu",
    "davao",
    "iloilo",
    "bacolod",
    "cagayan de oro",
    "zamboanga",
    "baguio",
    "dumaguete",
    "general santos",
    "naga city",
    "legazpi",
    "tacloban",
    "butuan",
    "batangas",
    "laguna",
    "los banos",
    "los baños",
    "cavite",
    "clark",
    "pampanga",
    "subic",
    "bulacan",
    "tarlac",
    "palawan",
    "boracay",
    "siargao",
)

# Institutions and companies that only run Philippine events.
_PH_ORGS = (
    "up diliman",
    "up manila",
    "up los banos",
    "up cebu",
    "university of the philippines",
    "ateneo",
    "de la salle",
    "dlsu",
    "ust",
    "university of santo tomas",
    "mapua",
    "mapúa",
    "adamson",
    "feu",
    "far eastern university",
    "national university philippines",
    "pup",
    "polytechnic university of the philippines",
    "silliman",
    "xavier university",
    "usc cebu",
    "dost",
    "dict",
    "egov",
    "egovph",
    "bangko sentral",
    "pldt",
    "globe telecom",
    "gcash",
    "smart communications",
    "ayala",
    "unionbank",
    "bpi",
    "shopee philippines",
    "grab philippines",
    "ideaspace",
    "qbo innovation",
)

_SEASIA_KEYWORDS = (
    "southeast asia",
    "south east asia",
    "south-east asia",
    "sea region",
    "asean",
    "apac",
    "asia pacific",
    "asia-pacific",
    "asia",
)

_GLOBAL_KEYWORDS = (
    "online",
    "virtual",
    "worldwide",
    "global",
    "anywhere",
    "remote",
    "internet",
)

# Bare "PH" appears in too many unrelated strings (pH sensors, file suffixes),
# so it only counts when it trails a location the way a country code does.
_PH_TOKEN_CONTEXT_RE = re.compile(
    r"(?:manila|cebu|davao|quezon|makati|taguig)\s*,\s*(?:ph|rp)\b",
    re.IGNORECASE,
)


def _compile(needles: Iterable[str]) -> "re.Pattern[str]":
    """Word-boundary alternation, longest first so the specific phrase wins.

    Substring matching is not safe here: "ncr" hides in "concrete", "ust" in
    "trust", "bpi" in arbitrary slugs.
    """
    ordered = sorted(needles, key=len, reverse=True)
    return re.compile(
        r"(?<!\w)(" + "|".join(re.escape(n) for n in ordered) + r")(?!\w)",
        re.IGNORECASE,
    )


_PH_KEYWORDS_RE = _compile(_PH_KEYWORDS)
_PH_CITIES_RE = _compile(_PH_CITIES)
_PH_ORGS_RE = _compile(_PH_ORGS)
_SEASIA_RE = _compile(_SEASIA_KEYWORDS)
_GLOBAL_RE = _compile(_GLOBAL_KEYWORDS)


def _first_hit(haystack: str, pattern: "re.Pattern[str]") -> str:
    match = pattern.search(haystack)
    return match.group(1).strip() if match else ""


def classify(text: str, is_online: bool = False) -> Tuple[str, str]:
    """Return `(tier, reason)` for a blob of listing text.

    `reason` is surfaced in output so a surprising ranking can be explained
    without re-running the matcher by hand.
    """
    blob = " ".join((text or "").lower().split())
    if not blob:
        return (PH_TIER_GLOBAL, "online listing") if is_online else (PH_TIER_NONE, "no location signal")

    hit = _first_hit(blob, _PH_KEYWORDS_RE)
    if hit:
        return PH_TIER_LOCAL, f"matched '{hit}'"

    hit = _first_hit(blob, _PH_CITIES_RE)
    if hit:
        return PH_TIER_LOCAL, f"Philippine city '{hit}'"

    hit = _first_hit(blob, _PH_ORGS_RE)
    if hit:
        return PH_TIER_LOCAL, f"Philippine organiser '{hit}'"

    if _PH_TOKEN_CONTEXT_RE.search(blob):
        return PH_TIER_LOCAL, "country code PH"

    hit = _first_hit(blob, _SEASIA_RE)
    if hit:
        return PH_TIER_SEASIA, f"regional scope '{hit}'"

    if is_online:
        return PH_TIER_GLOBAL, "online listing"

    hit = _first_hit(blob, _GLOBAL_RE)
    if hit:
        return PH_TIER_GLOBAL, f"open scope '{hit}'"

    return PH_TIER_NONE, "no Philippine or global signal"


def tier_rank(tier: str) -> int:
    """Lower is more relevant; used for stable sorting and merge preference."""
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return len(TIER_ORDER)
