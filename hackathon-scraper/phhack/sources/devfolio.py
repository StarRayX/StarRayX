"""Devfolio — large hackathon platform, strong Asia coverage.

Devfolio's directory is served by an Elasticsearch-backed search endpoint that
takes a JSON POST body and returns hits under ``hits.hits[]._source``.

EXPERIMENTAL: the endpoint is undocumented. The parser reads through the
lenient helpers and tolerates envelope changes, but if Devfolio reshapes its
records this adapter will return fewer rows rather than raise. Run with
``--dump-raw`` to inspect a live payload.
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

API_URL = "https://api.devfolio.co/api/search/hackathons"
PAGE_SIZE = 30


class DevfolioSource(Source):
    name = "devfolio"
    label = "Devfolio"
    homepage = "https://devfolio.co/hackathons"
    experimental = True
    default_currency = "USD"

    def fetch(self, ctx: FetchContext) -> List[Hackathon]:
        results: List[Hackathon] = []
        seen: set = set()

        queries = list(ctx.queries)
        if ctx.include_global:
            # An empty query returns the full open board.
            queries.append("")

        for query in queries:
            for page in range(ctx.max_pages):
                payload = ctx.http.post_json(
                    API_URL,
                    payload={
                        "type": "application_open",
                        "q": query,
                        "filter": "all",
                        "from": page * PAGE_SIZE,
                        "size": PAGE_SIZE,
                    },
                    label=f"devfolio_{query or 'global'}_p{page}",
                )
                records = find_records(payload, ("hits", "hits"), ("hackathons",))
                if not records:
                    break

                for record in records:
                    # Elasticsearch wraps the document; unwrap when present.
                    doc = record.get("_source") if isinstance(record.get("_source"), dict) else record
                    hackathon = self._parse(doc)
                    if hackathon is None or hackathon.url in seen:
                        continue
                    seen.add(hackathon.url)
                    results.append(hackathon)

                if len(records) < PAGE_SIZE:
                    break

        return results

    @staticmethod
    def _parse(record: Dict[str, Any]) -> Hackathon | None:
        slug = pick_str(record, "slug", "uuid", "hackathon_slug")
        url = pick_str(record, "url", "website")
        if not url and slug:
            url = f"https://{slug}.devfolio.co"

        settings = pick(record, "hackathon_setting", "settings", default={}) or {}
        location_text = pick_str(
            record, "location", "city", "venue"
        ) or pick_str(settings, "location", "city")

        is_online_raw = pick(record, "is_online", "online")
        if is_online_raw is None:
            is_online_raw = pick(settings, "is_online", "online")
        is_online = bool(is_online_raw) if is_online_raw is not None else None
        if is_online is None and location_text:
            is_online = "online" in location_text.lower()

        return make_hackathon(
            source=DevfolioSource.name,
            source_id=pick_str(record, "uuid", "id", "slug", default="") or "",
            title=pick_str(record, "name", "title", default="") or "",
            url=absolute_url(url),
            organizer=pick_str(record, "organizer", "company", "team_name"),
            location_text=location_text,
            is_online=is_online,
            starts_on=parse_any(pick(record, "starts_at", "start_date", "hackathon_starts_at")),
            ends_on=parse_any(pick(record, "ends_at", "end_date", "hackathon_ends_at")),
            deadline_text=pick_str(record, "apply_close_time", "deadline"),
            status=normalise_status(pick_str(record, "status", "state", "type")),
            prize_text=pick_str(record, "prize", "prizes", "total_prize", "reward"),
            participants=pick_int(record, "participants_count", "registrations", "hackers"),
            themes=names_of(pick(record, "themes", "tags", "tracks"), "name", "title"),
        )
