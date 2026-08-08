"""Source registry.

Adding a source means writing an adapter and appending it here — nothing else
in the pipeline needs to change.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

from .base import DEFAULT_QUERIES, FetchContext, Source
from .devfolio import DevfolioSource
from .devpost import DevpostSource
from .dorahacks import DoraHacksSource
from .hackerearth import HackerEarthSource
from .unstop import UnstopSource

ALL_SOURCES: Sequence[Source] = (
    DevpostSource(),
    DevfolioSource(),
    HackerEarthSource(),
    DoraHacksSource(),
    UnstopSource(),
)

SOURCES_BY_NAME: Dict[str, Source] = {s.name: s for s in ALL_SOURCES}

#: Enabled unless `--sources` narrows it. Experimental adapters are included
#: because they fail soft: a drifted schema costs a warning, not the run.
DEFAULT_SOURCE_NAMES: Sequence[str] = tuple(SOURCES_BY_NAME)


def resolve(names: Sequence[str]) -> List[Source]:
    """Map source names to instances, raising on an unknown name."""
    resolved: List[Source] = []
    for name in names:
        key = name.strip().lower()
        if not key:
            continue
        if key not in SOURCES_BY_NAME:
            known = ", ".join(sorted(SOURCES_BY_NAME))
            raise KeyError(f"unknown source '{name}' (known: {known})")
        resolved.append(SOURCES_BY_NAME[key])
    return resolved


def default_currency_for(source_name: str) -> str:
    source = SOURCES_BY_NAME.get(source_name)
    return source.default_currency if source else "USD"


__all__ = [
    "ALL_SOURCES",
    "SOURCES_BY_NAME",
    "DEFAULT_SOURCE_NAMES",
    "DEFAULT_QUERIES",
    "FetchContext",
    "Source",
    "resolve",
    "default_currency_for",
]
