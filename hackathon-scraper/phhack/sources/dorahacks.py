"""DoraHacks — Web3 buidl bounties, routinely the largest prize pools online.

Almost entirely remote, so nearly everything here lands in the ``global`` tier:
open to a Philippine team, and worth surfacing precisely because the pots are
large.

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

API_URL = "https://dorahacks.io/api/hackathon/"
PAGE_SIZE = 20


class DoraHacksSource(Source):
    name = "dorahacks"
    label = "DoraHacks"
    homepage = "https://dorahacks.io/hackathon"
    experimental = True
    default_currency = "USD"

    def fetch(self, ctx: FetchContext) -> List[Hackathon]:
        results: List[Hackathon] = []
        seen: set = set()

        for page in range(1, ctx.max_pages + 1):
            payload = ctx.http.get_json(
                API_URL,
                params={"page": page, "page_size": PAGE_SIZE},
                label=f"dorahacks_p{page}",
            )
            records = find_records(payload, ("results",), ("data",), ("hackathons",))
            if not records:
                break

            for record in records:
                hackathon = self._parse(record)
                if hackathon is None or hackathon.url in seen:
                    continue
                seen.add(hackathon.url)
                results.append(hackathon)

            if len(records) < PAGE_SIZE:
                break

        return results

    @staticmethod
    def _parse(record: Dict[str, Any]) -> Hackathon | None:
        slug = pick_str(record, "slug", "id", "hackathon_id")
        url = pick_str(record, "url", "link")
        if not url and slug:
            url = f"https://dorahacks.io/hackathon/{slug}/detail"

        return make_hackathon(
            source=DoraHacksSource.name,
            source_id=pick_str(record, "id", "slug", default="") or "",
            title=pick_str(record, "title", "name", default="") or "",
            url=absolute_url(url, base="https://dorahacks.io"),
            organizer=pick_str(record, "host", "organizer", "owner_name"),
            location_text=pick_str(record, "location", "city") or "Online",
            is_online=True,
            starts_on=parse_any(pick(record, "start_time", "start_date", "starts_at")),
            ends_on=parse_any(pick(record, "end_time", "end_date", "ends_at")),
            deadline_text=pick_str(record, "deadline"),
            status=normalise_status(pick_str(record, "status", "state")),
            prize_text=pick_str(record, "total_prize", "prize", "prize_pool", "reward"),
            participants=pick_int(record, "participants", "builder_count"),
            themes=names_of(pick(record, "tags", "tracks", "categories"), "name"),
        )
