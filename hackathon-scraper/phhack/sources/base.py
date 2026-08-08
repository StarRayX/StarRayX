"""Source adapter contract plus the lenient field-access helpers adapters share.

Every adapter reads a third-party JSON payload that can and does change shape
without notice. The helpers here exist so an adapter can ask for "whichever of
these keys exists" instead of hard-coding one spelling and crashing on drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set

from ..http import HttpClient
from ..models import (
    STATUS_ENDED,
    STATUS_OPEN,
    STATUS_UNKNOWN,
    STATUS_UPCOMING,
    Hackathon,
)

#: Search terms used against sources that support free-text query.
DEFAULT_QUERIES: Sequence[str] = (
    "philippines",
    "filipino",
    "manila",
    "cebu",
)


@dataclass
class FetchContext:
    """Everything an adapter needs for one run."""

    http: HttpClient
    queries: Sequence[str] = field(default_factory=lambda: list(DEFAULT_QUERIES))
    include_global: bool = True
    max_pages: int = 3
    statuses: Set[str] = field(
        default_factory=lambda: {STATUS_OPEN, STATUS_UPCOMING}
    )


class Source:
    """Base class for a listing source."""

    name: str = "base"
    label: str = "Base"
    homepage: str = ""
    #: True when the endpoint is undocumented and its schema is inferred rather
    #: than verified. Surfaced by `phhack sources` so a silent empty result from
    #: one of these reads as "may have drifted", not "nothing is happening".
    experimental: bool = False
    #: Currency to assume when a prize string carries a bare number or an
    #: ambiguous "$". Set per-platform: Unstop quotes INR, Devpost quotes USD.
    default_currency: str = "USD"

    def fetch(self, ctx: FetchContext) -> List[Hackathon]:
        raise NotImplementedError


# --- lenient accessors -------------------------------------------------


def pick(data: Any, *keys: str, default: Any = None) -> Any:
    """First present, non-empty value among `keys` in a mapping."""
    if not isinstance(data, dict):
        return default
    for key in keys:
        if key in data:
            value = data[key]
            if value not in (None, "", [], {}):
                return value
    return default


def pick_str(data: Any, *keys: str, default: Optional[str] = None) -> Optional[str]:
    value = pick(data, *keys)
    if value is None:
        return default
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return text or default
    return default


def pick_int(data: Any, *keys: str) -> Optional[int]:
    value = pick(data, *keys)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_list(value: Any) -> List[Any]:
    """Normalise scalar/None/list into a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def names_of(value: Any, *keys: str) -> List[str]:
    """Flatten a list of tag-ish objects or strings into plain names."""
    out: List[str] = []
    for item in as_list(value):
        if isinstance(item, str):
            text = item.strip()
            if text:
                out.append(text)
        elif isinstance(item, dict):
            text = pick_str(item, *(keys or ("name", "title", "label")))
            if text:
                out.append(text)
    return out


def find_records(payload: Any, *paths: Sequence[str]) -> List[Dict[str, Any]]:
    """Locate the list of records in a response, trying each dotted path.

    Falls back to a shallow scan for the first list-of-dicts, which keeps an
    adapter working when a provider renames its envelope but not its records.
    """
    for path in paths:
        node: Any = payload
        for key in path:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, list) and node:
            return [item for item in node if isinstance(item, dict)]

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list) and value and all(isinstance(i, dict) for i in value):
                return value
            if isinstance(value, dict):
                nested = find_records(value)
                if nested:
                    return nested
    return []


def normalise_status(raw: Any, fallback: str = STATUS_UNKNOWN) -> str:
    """Map a source's status vocabulary onto ours."""
    text = str(raw or "").strip().lower()
    if not text:
        return fallback
    if text in {"open", "live", "ongoing", "active", "application_open", "started", "running"}:
        return STATUS_OPEN
    if text in {"upcoming", "coming_soon", "announced", "registration_open", "future", "scheduled"}:
        return STATUS_UPCOMING
    if text in {"ended", "closed", "completed", "past", "finished", "over", "expired"}:
        return STATUS_ENDED
    if "open" in text or "live" in text:
        return STATUS_OPEN
    if "upcoming" in text or "soon" in text:
        return STATUS_UPCOMING
    if "end" in text or "clos" in text or "past" in text:
        return STATUS_ENDED
    return fallback


def absolute_url(url: Optional[str], base: str = "https://") -> str:
    """Repair protocol-relative and scheme-less URLs."""
    if not url:
        return ""
    text = str(url).strip()
    if text.startswith("//"):
        return "https:" + text
    if text.startswith(("http://", "https://")):
        return text
    return base.rstrip("/") + "/" + text.lstrip("/")


def make_hackathon(**kwargs: Any) -> Optional[Hackathon]:
    """Build a Hackathon, rejecting records that lack the required fields."""
    title = (kwargs.get("title") or "").strip()
    url = (kwargs.get("url") or "").strip()
    if not title or not url:
        return None
    kwargs["title"] = title
    kwargs["url"] = url
    return Hackathon(**kwargs)
