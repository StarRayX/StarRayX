"""The experimental adapters parse undocumented endpoints.

The contract they must honour is not "parse today's schema perfectly" — it is
"extract what is there, and degrade to an empty list instead of raising when the
provider changes shape". These tests pin that contract.
"""

from __future__ import annotations

from datetime import date

import pytest

from conftest import FakeHttp

from phhack.sources import ALL_SOURCES, FetchContext, resolve
from phhack.sources.devfolio import DevfolioSource
from phhack.sources.dorahacks import DoraHacksSource
from phhack.sources.hackerearth import HackerEarthSource
from phhack.sources.unstop import UnstopSource

EXPERIMENTAL = [DevfolioSource, HackerEarthSource, DoraHacksSource, UnstopSource]

#: Shapes a drifting provider realistically returns.
DRIFT_PAYLOADS = [
    {},
    {"data": None},
    {"results": []},
    {"hits": {"hits": []}},
    {"totally": {"different": "envelope"}},
    [],
    {"data": {"data": [{"no_title": True, "no_url": True}]}},
]


def ctx_for(payloads):
    return FetchContext(
        http=FakeHttp(payloads), queries=["philippines"], include_global=False, max_pages=1
    )


@pytest.mark.parametrize("source_cls", EXPERIMENTAL)
@pytest.mark.parametrize("payload", DRIFT_PAYLOADS)
def test_schema_drift_yields_no_rows_rather_than_an_exception(source_cls, payload):
    assert source_cls().fetch(ctx_for([payload])) == []


@pytest.mark.parametrize("source_cls", EXPERIMENTAL)
def test_records_missing_title_or_url_are_skipped(source_cls):
    payload = {
        "results": [{"id": 1}],
        "data": {"data": [{"id": 1}]},
        "hits": {"hits": [{"_source": {"id": 1}}]},
        "response": [{"id": 1}],
    }
    assert source_cls().fetch(ctx_for([payload])) == []


def test_devfolio_builds_urls_from_slugs():
    payload = {"hits": {"hits": [{"_source": {
        "name": "Manila Buildathon", "slug": "manila-build",
        "starts_at": "2026-04-01T00:00:00Z", "ends_at": "2026-04-03T00:00:00Z",
        "is_online": False, "city": "Manila", "prize": "$12,000",
    }}]}}
    item = DevfolioSource().fetch(ctx_for([payload]))[0]

    assert item.url == "https://manila-build.devfolio.co"
    assert item.title == "Manila Buildathon"
    assert item.starts_on == date(2026, 4, 1)
    assert item.ends_on == date(2026, 4, 3)
    assert item.is_online is False
    assert item.prize_text == "$12,000"


def test_hackerearth_reads_the_extension_feed():
    payload = {"response": [{
        "title": "Fintech Challenge", "url": "https://www.hackerearth.com/challenges/ft/",
        "start_tz": "2026-05-01T09:00:00", "end_tz": "2026-05-15T09:00:00",
        "challenge_type": "Online Challenge", "status": "ongoing",
        "prizes": "$5,000", "company_name": "Sponsor Co",
    }]}
    item = HackerEarthSource().fetch(ctx_for([payload]))[0]

    assert item.title == "Fintech Challenge"
    assert item.is_online is True
    assert item.status == "open"
    assert item.organizer == "Sponsor Co"
    assert item.starts_on == date(2026, 5, 1)


def test_hackerearth_repairs_relative_urls():
    payload = {"response": [{"title": "X", "url": "/challenges/x/"}]}
    item = HackerEarthSource().fetch(ctx_for([payload]))[0]
    assert item.url == "https://www.hackerearth.com/challenges/x/"


def test_dorahacks_marks_everything_online():
    payload = {"results": [{
        "title": "Web3 Grant Hack", "slug": "web3-grant",
        "total_prize": "$250,000", "start_time": 1777000000, "end_time": 1779000000,
    }]}
    item = DoraHacksSource().fetch(ctx_for([payload]))[0]

    assert item.url == "https://dorahacks.io/hackathon/web3-grant/detail"
    assert item.is_online is True
    assert item.prize_text == "$250,000"
    assert item.starts_on is not None


def test_unstop_flattens_structured_prize_lists():
    payload = {"data": {"data": [{
        "id": 77, "title": "Campus Hack", "public_url": "https://unstop.com/o/campus",
        "prizes": [{"cash": "₹1,00,000"}, {"cash": "₹50,000"}],
        "organisation": {"name": "Some University"}, "region": "Online",
    }]}}
    item = UnstopSource().fetch(ctx_for([payload]))[0]

    assert item.organizer == "Some University"
    assert item.is_online is True
    assert "1,00,000" in item.prize_text


def test_unstop_defaults_to_inr():
    assert UnstopSource().default_currency == "INR"


# --- registry ----------------------------------------------------------


def test_every_source_declares_its_metadata():
    for source in ALL_SOURCES:
        assert source.name and source.label and source.homepage
        assert source.default_currency


def test_source_names_are_unique():
    names = [s.name for s in ALL_SOURCES]
    assert len(names) == len(set(names))


def test_resolve_rejects_unknown_names():
    with pytest.raises(KeyError):
        resolve(["devpost", "not-a-source"])


def test_resolve_is_case_insensitive():
    assert resolve(["DevPost"])[0].name == "devpost"
