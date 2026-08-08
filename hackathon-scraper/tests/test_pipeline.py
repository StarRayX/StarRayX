"""End-to-end pipeline behaviour, entirely offline."""

from __future__ import annotations



import pytest

from conftest import TODAY, FakeHttp, load_fixture, make

from phhack.geo import PH_TIER_GLOBAL, PH_TIER_LOCAL, PH_TIER_SEASIA
from phhack.http import FetchError
from phhack.models import STATUS_OPEN, STATUS_UPCOMING
from phhack.pipeline import collect, enrich, filter_listings, run
from phhack.sources import FetchContext, Source
from phhack.sources.devpost import DevpostSource


class ExplodingSource(Source):
    name = "boom"
    label = "Boom"

    def fetch(self, ctx):
        raise FetchError("endpoint moved")


class StubSource(Source):
    name = "stub"
    label = "Stub"

    def __init__(self, items):
        self._items = items

    def fetch(self, ctx):
        return list(self._items)


@pytest.fixture
def devpost_ctx():
    http = FakeHttp([load_fixture("devpost_page1.json")])
    return FetchContext(http=http, queries=["philippines"], include_global=False, max_pages=1)


# --- collect -----------------------------------------------------------


def test_one_failing_source_does_not_lose_the_others(devpost_ctx):
    from phhack.pipeline import RunReport

    report = RunReport()
    items = collect([ExplodingSource(), DevpostSource()], devpost_ctx, report=report)

    assert len(items) == 5, "healthy source results must survive"
    assert "boom" in report.errors
    assert "endpoint moved" in report.errors["boom"]
    assert report.fetched["devpost"] == 5


def test_strict_mode_propagates_failures(devpost_ctx):
    with pytest.raises(FetchError):
        collect([ExplodingSource()], devpost_ctx, strict=True)


# --- enrich ------------------------------------------------------------


def test_enrich_converts_prizes_to_php(devpost_ctx):
    by_title = {h.title: h for h in enrich(DevpostSource().fetch(devpost_ctx))}

    usd = by_title["Bayanihan Build 2026"]
    assert usd.prize_currency == "USD"
    assert usd.prize_amount == pytest.approx(25_000)
    assert usd.prize_php == pytest.approx(25_000 * 58.0)

    php = by_title["Cebu Fintech Sprint"]
    assert php.prize_currency == "PHP"
    assert php.prize_php == pytest.approx(750_000)


def test_enrich_leaves_unknown_prizes_as_none(devpost_ctx):
    by_title = {h.title: h for h in enrich(DevpostSource().fetch(devpost_ctx))}
    assert by_title["Quiet Hack With No Prize"].prize_php is None


def test_enrich_assigns_relevance_tiers(devpost_ctx):
    by_title = {h.title: h for h in enrich(DevpostSource().fetch(devpost_ctx))}
    assert by_title["Bayanihan Build 2026"].ph_tier == PH_TIER_LOCAL
    assert by_title["Cebu Fintech Sprint"].ph_tier == PH_TIER_LOCAL
    assert by_title["Global Agents Hack"].ph_tier == PH_TIER_GLOBAL
    assert by_title["Oktoberfest Code Jam"].ph_tier == "none"


def test_enrich_honours_custom_fx_rates(devpost_ctx):
    items = enrich(DevpostSource().fetch(devpost_ctx), rates={"USD": 1.0, "PHP": 1.0})
    usd = next(h for h in items if h.title == "Bayanihan Build 2026")
    assert usd.prize_php == pytest.approx(25_000)


# --- filtering ---------------------------------------------------------


def test_filter_drops_irrelevant_tiers():
    items = [make(ph_tier=PH_TIER_LOCAL), make(ph_tier="none")]
    assert len(filter_listings(items, tiers={PH_TIER_LOCAL})) == 1


def test_min_prize_keeps_unpublished_prizes_by_default():
    """'Prize not announced' is not the same as 'prize too small'."""
    items = [
        make(title="unknown", ph_tier=PH_TIER_LOCAL, prize_php=None),
        make(title="small", ph_tier=PH_TIER_LOCAL, prize_php=1_000),
    ]
    kept = filter_listings(items, tiers={PH_TIER_LOCAL}, min_prize_php=500_000)
    assert [h.title for h in kept] == ["unknown"]


def test_require_prize_drops_them():
    items = [make(ph_tier=PH_TIER_LOCAL, prize_php=None)]
    assert filter_listings(items, tiers={PH_TIER_LOCAL}, require_prize=True) == []


def test_unknown_status_is_kept():
    """Several sources omit status entirely; dropping those hides real events."""
    items = [make(ph_tier=PH_TIER_LOCAL, status="unknown")]
    assert len(filter_listings(items, tiers={PH_TIER_LOCAL}, statuses={STATUS_OPEN})) == 1


def test_explicit_wrong_status_is_dropped():
    items = [make(ph_tier=PH_TIER_LOCAL, status="ended")]
    assert filter_listings(items, tiers={PH_TIER_LOCAL}, statuses={STATUS_OPEN}) == []


# --- full run ----------------------------------------------------------


def test_run_ranks_by_prize_and_excludes_irrelevant(devpost_ctx):
    listings, report = run(
        sources=[DevpostSource()],
        ctx=devpost_ctx,
        tiers={PH_TIER_LOCAL, PH_TIER_SEASIA, PH_TIER_GLOBAL},
        statuses={STATUS_OPEN, STATUS_UPCOMING},
        sort_mode="prize",
        today=TODAY,
    )
    titles = [h.title for h in listings]

    # $1M global pot first, then $25K Manila, then ₱750K Cebu, unknown last.
    assert titles == [
        "Global Agents Hack",
        "Bayanihan Build 2026",
        "Cebu Fintech Sprint",
        "Quiet Hack With No Prize",
    ]
    assert "Oktoberfest Code Jam" not in titles  # tier 'none', filtered out
    assert report.total_raw == 5
    assert report.after_dedupe == 4


def test_run_respects_min_prize_and_limit(devpost_ctx):
    listings, _ = run(
        sources=[DevpostSource()],
        ctx=devpost_ctx,
        tiers={PH_TIER_LOCAL, PH_TIER_GLOBAL},
        min_prize_php=1_000_000,
        require_prize=True,
        limit=1,
        today=TODAY,
    )
    assert [h.title for h in listings] == ["Global Agents Hack"]


def test_ph_only_run_excludes_global_pots(devpost_ctx):
    listings, _ = run(
        sources=[DevpostSource()],
        ctx=devpost_ctx,
        tiers={PH_TIER_LOCAL},
        today=TODAY,
    )
    assert [h.title for h in listings] == ["Bayanihan Build 2026", "Cebu Fintech Sprint"]


def test_run_scores_every_listing(devpost_ctx):
    listings, _ = run(
        sources=[DevpostSource()],
        ctx=devpost_ctx,
        tiers={PH_TIER_LOCAL, PH_TIER_GLOBAL},
        today=TODAY,
    )
    assert all(0.0 < h.score <= 100.0 for h in listings)


def test_run_merges_duplicates_across_sources(devpost_ctx):
    duplicate = make(
        title="Global Agents Hack",
        source="devfolio",
        url="https://global-agents.devfolio.co",
        is_online=True,
    )
    listings, report = run(
        sources=[DevpostSource(), StubSource([duplicate])],
        ctx=devpost_ctx,
        tiers={PH_TIER_LOCAL, PH_TIER_GLOBAL},
        today=TODAY,
    )
    assert report.total_raw == 6
    winner = next(h for h in listings if h.title == "Global Agents Hack")
    assert winner.source == "devpost"
    assert "devfolio" in winner.also_seen_on
