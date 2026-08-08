"""Unstop — competition aggregator with a growing Southeast Asia section.

Prizes are usually denominated in INR, so the default currency differs from the
other adapters; conversion to PHP happens in the pipeline.

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

API_URL = "https://unstop.com/api/public/opportunity/search-result"
PAGE_SIZE = 30


class UnstopSource(Source):
    name = "unstop"
    label = "Unstop"
    homepage = "https://unstop.com/hackathons"
    experimental = True
    default_currency = "INR"

    def fetch(self, ctx: FetchContext) -> List[Hackathon]:
        results: List[Hackathon] = []
        seen: set = set()

        for query in ctx.queries:
            for page in range(1, ctx.max_pages + 1):
                payload = ctx.http.get_json(
                    API_URL,
                    params={
                        "opportunity": "hackathons",
                        "page": page,
                        "per_page": PAGE_SIZE,
                        "oppstatus": "open",
                        "searchTerm": query,
                    },
                    label=f"unstop_{query}_p{page}",
                )
                records = find_records(payload, ("data", "data"), ("data",))
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
        url = pick_str(record, "public_url", "seo_url", "url")
        if url and not url.startswith("http"):
            url = absolute_url(url, base="https://unstop.com")

        organisation = pick(record, "organisation", "organization", default={}) or {}
        organizer = (
            pick_str(organisation, "name")
            if isinstance(organisation, dict)
            else str(organisation)
        )

        region = pick_str(record, "region", "location", "city")
        is_online = None
        if region:
            is_online = region.lower() in {"online", "virtual"}

        return make_hackathon(
            source=UnstopSource.name,
            source_id=pick_str(record, "id", "uuid", default="") or "",
            title=pick_str(record, "title", "name", default="") or "",
            url=url or "",
            organizer=organizer,
            location_text=region,
            is_online=is_online,
            starts_on=parse_any(pick(record, "start_date", "startDate")),
            ends_on=parse_any(pick(record, "end_date", "endDate", "regnRequirements")),
            deadline_text=pick_str(record, "remain_days", "days_left"),
            status=normalise_status(pick_str(record, "status", "opportunity_status")),
            prize_text=_prize_text(record),
            participants=pick_int(record, "registerCount", "views_count"),
            themes=names_of(pick(record, "filters", "tags", "categories"), "name"),
        )


def _prize_text(record: Dict[str, Any]) -> str | None:
    """Flatten Unstop's structured prize list into text the parser can read."""
    direct = pick_str(record, "prize", "prizes", "total_prize")
    if direct:
        return direct

    prizes = pick(record, "prizes", default=[]) or []
    parts: List[str] = []
    for item in prizes if isinstance(prizes, list) else []:
        if isinstance(item, dict):
            cash = pick_str(item, "cash", "amount", "prize_amount", "value")
            if cash:
                parts.append(cash)
        elif isinstance(item, (str, int, float)):
            parts.append(str(item))
    return " ".join(parts) if parts else None
