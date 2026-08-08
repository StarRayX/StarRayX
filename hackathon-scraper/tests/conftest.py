"""Shared test helpers. Nothing here touches the network."""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Any, Dict, List

import pytest

from phhack.models import Hackathon

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

#: Fixed "today" so date-sensitive assertions stay stable over time.
TODAY = date(2026, 2, 20)


def load_fixture(name: str) -> Any:
    with open(os.path.join(FIXTURE_DIR, name), "r", encoding="utf-8") as handle:
        return json.load(handle)


class FakeHttp:
    """Stand-in for HttpClient that replays canned payloads.

    Returns the queued payload for each successive call and repeats the last
    one afterwards, so pagination loops terminate naturally on an empty page.
    """

    def __init__(self, payloads: List[Any], fail_with: Exception = None) -> None:
        self._payloads = list(payloads)
        self._index = 0
        self._fail_with = fail_with
        self.calls: List[Dict[str, Any]] = []

    def _next(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append({"method": method, "url": url, **kwargs})
        if self._fail_with is not None:
            raise self._fail_with
        if self._index < len(self._payloads):
            payload = self._payloads[self._index]
            self._index += 1
            return payload
        return {}

    def get_json(self, url: str, params: Any = None, headers: Any = None, label: str = "") -> Any:
        return self._next("GET", url, params=params, label=label)

    def post_json(self, url: str, payload: Any = None, headers: Any = None, label: str = "") -> Any:
        return self._next("POST", url, payload=payload, label=label)

    def get_text(self, url: str, params: Any = None, headers: Any = None, label: str = "") -> str:
        return json.dumps(self._next("GET", url, params=params, label=label))


def make(
    title: str = "Test Hack",
    url: str = "https://example.devpost.com/",
    source: str = "devpost",
    **kwargs: Any,
) -> Hackathon:
    """Build a Hackathon with sensible defaults for focused assertions."""
    return Hackathon(source=source, title=title, url=url, **kwargs)


@pytest.fixture
def today() -> date:
    return TODAY
