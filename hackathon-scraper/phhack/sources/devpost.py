"""Devpost — the primary source.

Devpost backs its public hackathon directory with a JSON endpoint at
``/api/hackathons``. It is the best source here for two reasons: it hosts most
online hackathons a Philippine team can enter, and it can sort server-side by
prize amount, so the biggest pots arrive on page one.

Query parameters used:
  ``search``            free-text
  ``page``              1-indexed
  ``order_by``          ``prize-amount`` | ``deadline`` | ``recently-added``
  ``status[]``          ``open`` | ``upcoming`` | ``ended``
  ``challenge_type[]``  ``online`` | ``in-person``
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..dates import parse_range
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

API_URL = "https://devpost.com/api/hackathons"


class DevpostSource(Source):
    name = "devpost"
    label = "Devpost"
    homepage = "https://devpost.com/hackathons"
    experimental = False

    def fetch(self, ctx: FetchContext) -> List[Hackathon]:
        results: List[Hackathon] = []
        seen_ids: set = set()

        # Pass 1: Philippines-targeted text searches.
        for query in ctx.queries:
            results.extend(self._search(ctx, seen_ids, search=query))

        # Pass 2: the global online board sorted by prize, which is where the
        # large pots live. Filtered down to PH-eligible entries later.
        if ctx.include_global:
            results.extend(
                self._search(ctx, seen_ids, search="", challenge_type="online")
            )

        return results

    def _search(
        self,
        ctx: FetchContext,
        seen_ids: set,
        search: str,
        challenge_type: str = "",
    ) -> List[Hackathon]:
        found: List[Hackathon] = []

        for page in range(1, ctx.max_pages + 1):
            params: List[tuple] = [
                ("search", search),
                ("page", str(page)),
                ("order_by", "prize-amount"),
            ]
            for status in sorted(ctx.statuses):
                params.append(("status[]", status))
            if challenge_type:
                params.append(("challenge_type[]", challenge_type))

            label = f"devpost_{search or 'global'}_{challenge_type or 'any'}_p{page}"
            payload = ctx.http.get_json(API_URL, params=params, label=label)

            records = find_records(payload, ("hackathons",))
            if not records:
                break

            for record in records:
                identifier = pick_str(record, "id", "analytics_identifier") or ""
                if identifier and identifier in seen_ids:
                    continue
                hackathon = self._parse(record)
                if hackathon is None:
                    continue
                if identifier:
                    seen_ids.add(identifier)
                found.append(hackathon)

            if self._is_last_page(payload, page, len(records)):
                break

        return found

    @staticmethod
    def _is_last_page(payload: Any, page: int, count: int) -> bool:
        meta = payload.get("meta") if isinstance(payload, dict) else None
        total = pick_int(meta or {}, "total_count", "total")
        per_page = pick_int(meta or {}, "per_page") or count or 1
        if total is not None:
            return page * per_page >= total
        return count == 0

    @staticmethod
    def _parse(record: Dict[str, Any]) -> Hackathon | None:
        location_block = pick(record, "displayed_location", default={}) or {}
        location_text = (
            pick_str(location_block, "location")
            if isinstance(location_block, dict)
            else str(location_block)
        )

        # Devpost has no boolean for this; "Online" in the location slot is the
        # signal the site itself renders from.
        is_online = bool(location_text and "online" in location_text.lower())

        period = pick_str(record, "submission_period_dates")
        starts_on, ends_on = parse_range(period)

        return make_hackathon(
            source=DevpostSource.name,
            source_id=pick_str(record, "id", "analytics_identifier", default="") or "",
            title=pick_str(record, "title", default="") or "",
            url=absolute_url(pick_str(record, "url")),
            organizer=pick_str(record, "organization_name"),
            location_text=location_text,
            is_online=is_online,
            starts_on=starts_on,
            ends_on=ends_on,
            deadline_text=pick_str(record, "time_left_to_submission"),
            status=normalise_status(pick_str(record, "open_state")),
            # Arrives as an HTML fragment; money.parse_prize strips it.
            prize_text=pick_str(record, "prize_amount"),
            participants=pick_int(record, "registrations_count"),
            themes=names_of(pick(record, "themes"), "name"),
        )
