"""Devpost adapter, driven by a fixture captured from the real response shape."""

from __future__ import annotations

from datetime import date

import pytest

from conftest import FakeHttp, load_fixture

from phhack.models import STATUS_OPEN, STATUS_UPCOMING
from phhack.sources import FetchContext
from phhack.sources.devpost import DevpostSource


@pytest.fixture
def listings():
    payload = load_fixture("devpost_page1.json")
    http = FakeHttp([payload])
    ctx = FetchContext(http=http, queries=["philippines"], include_global=False, max_pages=1)
    return {h.title: h for h in DevpostSource().fetch(ctx)}


def test_parses_every_record(listings):
    assert len(listings) == 5


def test_extracts_core_fields(listings):
    item = listings["Bayanihan Build 2026"]
    assert item.source == "devpost"
    assert item.source_id == "24101"
    assert item.url == "https://bayanihan-build.devpost.com/"
    assert item.organizer == "DICT Philippines"
    assert item.location_text == "Manila, Philippines"
    assert item.status == STATUS_OPEN
    assert item.participants == 812
    assert item.themes == ["Social Good", "Machine Learning/AI"]


def test_parses_submission_period_into_dates(listings):
    item = listings["Bayanihan Build 2026"]
    assert item.starts_on == date(2026, 2, 2)
    assert item.ends_on == date(2026, 3, 20)


def test_repairs_protocol_relative_urls(listings):
    assert listings["Global Agents Hack"].url == "https://global-agents.devpost.com/"


def test_detects_online_from_the_location_slot(listings):
    assert listings["Global Agents Hack"].is_online is True
    assert listings["Bayanihan Build 2026"].is_online is False


def test_keeps_prize_markup_for_the_parser(listings):
    # The adapter deliberately does not parse money; that happens in enrich()
    # so every source shares one implementation.
    assert "25,000" in listings["Bayanihan Build 2026"].prize_text


def test_maps_status_vocabulary(listings):
    assert listings["Oktoberfest Code Jam"].status == STATUS_UPCOMING


def test_missing_prize_is_none_not_empty(listings):
    assert not listings["Quiet Hack With No Prize"].prize_text


def test_null_organizer_survives(listings):
    assert listings["Quiet Hack With No Prize"].organizer is None


def test_requests_prize_ordering_and_status_filters():
    http = FakeHttp([load_fixture("devpost_page1.json")])
    ctx = FetchContext(
        http=http, queries=["philippines"], include_global=False, max_pages=1,
        statuses={"open", "upcoming"},
    )
    DevpostSource().fetch(ctx)

    params = dict(
        (key, value) for key, value in http.calls[0]["params"] if key != "status[]"
    )
    statuses = [v for k, v in http.calls[0]["params"] if k == "status[]"]
    assert params["order_by"] == "prize-amount"
    assert params["search"] == "philippines"
    assert sorted(statuses) == ["open", "upcoming"]


def test_global_pass_requests_online_challenges():
    http = FakeHttp([load_fixture("devpost_page1.json")])
    ctx = FetchContext(http=http, queries=[], include_global=True, max_pages=1)
    DevpostSource().fetch(ctx)

    types = [v for k, v in http.calls[0]["params"] if k == "challenge_type[]"]
    assert types == ["online"]


def test_stops_paginating_at_total_count():
    # meta.total_count is 5 with per_page 10, so one page covers everything.
    http = FakeHttp([load_fixture("devpost_page1.json")])
    ctx = FetchContext(http=http, queries=["philippines"], include_global=False, max_pages=5)
    DevpostSource().fetch(ctx)
    assert len(http.calls) == 1


def test_deduplicates_ids_across_queries():
    payload = load_fixture("devpost_page1.json")
    http = FakeHttp([payload, payload])
    ctx = FetchContext(
        http=http, queries=["philippines", "manila"], include_global=False, max_pages=1
    )
    results = DevpostSource().fetch(ctx)
    assert len(http.calls) == 2  # both queries ran
    assert len(results) == 5  # but the same events were not duplicated


def test_tolerates_an_unexpected_envelope():
    """Schema drift should yield nothing, not an exception."""
    http = FakeHttp([{"unexpected": "shape"}])
    ctx = FetchContext(http=http, queries=["philippines"], include_global=False, max_pages=1)
    assert DevpostSource().fetch(ctx) == []


def test_skips_records_missing_required_fields():
    http = FakeHttp([{"hackathons": [{"id": 1, "title": "", "url": ""}], "meta": {}}])
    ctx = FetchContext(http=http, queries=["x"], include_global=False, max_pages=1)
    assert DevpostSource().fetch(ctx) == []
