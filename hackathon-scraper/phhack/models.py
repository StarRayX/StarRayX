"""Core data model shared by every source adapter."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

# Lifecycle of a listing. Sources report this inconsistently, so adapters
# normalise onto these four values and `unknown` is always acceptable.
STATUS_OPEN = "open"
STATUS_UPCOMING = "upcoming"
STATUS_ENDED = "ended"
STATUS_UNKNOWN = "unknown"

VALID_STATUSES = (STATUS_OPEN, STATUS_UPCOMING, STATUS_ENDED, STATUS_UNKNOWN)


@dataclass
class Hackathon:
    """A single hackathon listing, normalised across sources.

    Only `source`, `title` and `url` are guaranteed. Everything else is
    best-effort: sources omit fields freely and adapters must not invent data
    to fill the gaps, because a missing prize and a zero prize rank very
    differently.
    """

    source: str
    title: str
    url: str

    source_id: str = ""
    organizer: Optional[str] = None

    # Location as printed by the source, plus whether it can be joined remotely.
    location_text: Optional[str] = None
    is_online: Optional[bool] = None

    starts_on: Optional[date] = None
    ends_on: Optional[date] = None
    # Free-text deadline ("22 days left") for sources that give no real dates.
    deadline_text: Optional[str] = None
    status: str = STATUS_UNKNOWN

    # Prize as printed, then parsed, then converted to PHP for cross-source
    # comparison. `prize_php` is the only field ranking looks at.
    prize_text: Optional[str] = None
    prize_amount: Optional[float] = None
    prize_currency: Optional[str] = None
    prize_php: Optional[float] = None

    participants: Optional[int] = None
    themes: List[str] = field(default_factory=list)

    # Derived by the pipeline, not by adapters.
    ph_tier: str = "none"
    ph_reason: str = ""
    score: float = 0.0
    also_seen_on: List[str] = field(default_factory=list)

    def searchable_text(self) -> str:
        """Everything a location/keyword matcher should look at."""
        parts = [
            self.title,
            self.organizer or "",
            self.location_text or "",
            self.url,
            " ".join(self.themes),
        ]
        return " ".join(p for p in parts if p)

    def to_dict(self) -> Dict[str, Any]:
        out = dataclasses.asdict(self)
        for key in ("starts_on", "ends_on"):
            value = out.get(key)
            out[key] = value.isoformat() if isinstance(value, date) else None
        return out
