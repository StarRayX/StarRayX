"""HackerEarth — sponsored challenges, frequently with sizeable prize pools.

Uses the JSON feed that backs HackerEarth's browser extension, which lists
current and upcoming challenges without authentication.

EXPERIMENTAL: undocumented endpoint; parsed leniently.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..dates import parse_any
from ..models import Hackathon
from .base import (
    FetchContext,
    Source,
    absolute_url,
    find_records,
    make_hackathon,
    names_of,
    normalise_status,
    pick,
    pick_int,
    pick_str,
)

log = logging.getLogger(__name__)

API_URL = "https://www.hackerearth.com/chrome-extension/events/"


class HackerEarthSource(Source):
    name = "hackerearth"
    label = "HackerEarth"
    homepage = "https://www.hackerearth.com/challenges/"
    experimental = True
    default_currency = "USD"

    def fetch(self, ctx: FetchContext) -> List[Hackathon]:
        # The feed is a single un-paginated dump, so it is fetched once and
        # filtered downstream rather than queried per search term.
        payload = ctx.http.get_json(API_URL, label="hackerearth_events")
        records = find_records(payload, ("response",), ("events",), ("data",))

        results: List[Hackathon] = []
        seen: set = set()
        for record in records:
            hackathon = self._parse(record)
            if hackathon is None or hackathon.url in seen:
                continue
            seen.add(hackathon.url)
            results.append(hackathon)
        return results

    @staticmethod
    def _parse(record: Dict[str, Any]) -> Hackathon | None:
        challenge_type = (pick_str(record, "challenge_type", "type") or "").lower()
        location_text = pick_str(record, "city", "location", "venue")
        is_online = None
        if challenge_type:
            is_online = "online" in challenge_type
        elif location_text:
            is_online = "online" in location_text.lower()

        return make_hackathon(
            source=HackerEarthSource.name,
            source_id=pick_str(record, "id", "slug", default="") or "",
            title=pick_str(record, "title", "name", default="") or "",
            url=absolute_url(
                pick_str(record, "url", "challenge_url", "absolute_url"),
                base="https://www.hackerearth.com",
            ),
            organizer=pick_str(record, "company_name", "organiser", "organizer", "host"),
            location_text=location_text,
            is_online=is_online,
            starts_on=parse_any(pick(record, "start_tz", "start_utc_tz", "start_date")),
            ends_on=parse_any(pick(record, "end_tz", "end_utc_tz", "end_date")),
            deadline_text=pick_str(record, "time_left", "ends_in"),
            status=normalise_status(pick_str(record, "status", "state")),
            prize_text=pick_str(record, "prizes", "prize", "reward", "prize_money"),
            participants=pick_int(record, "participants", "registrations_count"),
            themes=names_of(pick(record, "tags", "categories", "skills"), "name"),
        )
