from __future__ import annotations

from datetime import date, timedelta

import pytest

from conftest import TODAY, make

from phhack.dedup import dedupe, title_key, url_key
from phhack.models import STATUS_ENDED
from phhack.rank import (
    PRIZE_CAP_PHP,
    prize_component,
    score,
    sort_hackathons,
    urgency_component,
)


# --- prize component ---------------------------------------------------


def test_bigger_prize_always_scores_higher():
    assert prize_component(5_000) < prize_component(500_000) < prize_component(5_000_000)


def test_prize_component_saturates_at_the_cap():
    assert prize_component(PRIZE_CAP_PHP) == pytest.approx(1.0)
    assert prize_component(PRIZE_CAP_PHP * 100) == pytest.approx(1.0)


def test_unknown_prize_beats_a_zero_prize_but_loses_to_a_real_one():
    assert 0.0 < prize_component(None) < prize_component(200_000)


def test_log_scale_keeps_local_events_competitive():
    """A huge global pot must not flatten a solid local prize to nothing.

    This is the whole reason the prize component is log-scaled.
    """
    local = prize_component(500_000)
    whale = prize_component(50_000_000)
    assert local / whale > 0.5


# --- urgency -----------------------------------------------------------


def test_urgency_peaks_about_a_month_out():
    near = urgency_component(make(ends_on=TODAY + timedelta(days=30)), TODAY)
    far = urgency_component(make(ends_on=TODAY + timedelta(days=200)), TODAY)
    assert near > far


def test_past_and_ended_listings_have_no_urgency():
    assert urgency_component(make(ends_on=TODAY - timedelta(days=1)), TODAY) == 0.0
    assert urgency_component(make(status=STATUS_ENDED, ends_on=TODAY + timedelta(days=5)), TODAY) == 0.0


def test_missing_dates_are_neutral_not_zero():
    assert urgency_component(make(), TODAY) > 0.0


# --- scoring and sorting ----------------------------------------------


def test_prize_dominates_the_score():
    rich_global = make(prize_php=3_000_000, ph_tier="global", ends_on=TODAY + timedelta(days=40))
    poor_local = make(prize_php=20_000, ph_tier="local", ends_on=TODAY + timedelta(days=40))
    assert score(rich_global, TODAY) > score(poor_local, TODAY)


def test_relevance_breaks_ties_between_equal_prizes():
    local = make(prize_php=500_000, ph_tier="local", ends_on=TODAY + timedelta(days=40))
    globalish = make(prize_php=500_000, ph_tier="global", ends_on=TODAY + timedelta(days=40))
    assert score(local, TODAY) > score(globalish, TODAY)


def test_sort_by_prize_puts_unknown_prizes_last():
    items = [
        make(title="unknown", prize_php=None),
        make(title="small", prize_php=1_000),
        make(title="big", prize_php=9_000_000),
    ]
    assert [h.title for h in sort_hackathons(items, "prize")] == ["big", "small", "unknown"]


def test_sort_by_deadline_puts_soonest_first():
    items = [
        make(title="late", ends_on=date(2026, 12, 1)),
        make(title="soon", ends_on=date(2026, 3, 1)),
        make(title="mid", ends_on=date(2026, 6, 1)),
    ]
    assert [h.title for h in sort_hackathons(items, "deadline")] == ["soon", "mid", "late"]


def test_sort_by_deadline_puts_undated_last():
    items = [make(title="dated", ends_on=date(2026, 3, 1)), make(title="undated")]
    assert [h.title for h in sort_hackathons(items, "deadline")] == ["dated", "undated"]


def test_unknown_sort_mode_is_rejected():
    with pytest.raises(ValueError):
        sort_hackathons([], "nonsense")


# --- de-duplication ----------------------------------------------------


def test_title_key_ignores_year_case_and_filler():
    assert title_key("TECHATHLON 2026 Hackathon") == title_key("Techathlon Hackathon (2026)")


def test_title_key_keeps_distinct_events_apart():
    assert title_key("Bayanihan Build") != title_key("Cebu Fintech Sprint")


def test_title_key_of_pure_filler_does_not_collapse_everything():
    assert title_key("The Hackathon") != title_key("The Challenge")


def test_url_key_strips_www():
    assert url_key("https://www.example.com/a") == url_key("https://example.com/b")


def test_merges_the_same_event_across_sources():
    merged = dedupe(
        [
            make(title="Bayanihan Build 2026", source="devpost", prize_php=1_450_000,
                 url="https://bayanihan.devpost.com/", organizer="DICT"),
            make(title="Bayanihan Build", source="unstop", prize_php=None,
                 url="https://unstop.com/o/bayanihan"),
        ]
    )
    assert len(merged) == 1
    assert merged[0].source == "devpost"  # richer record wins
    assert merged[0].also_seen_on == ["unstop"]


def test_richer_duplicate_replaces_the_first_seen_one():
    merged = dedupe(
        [
            make(title="Cebu Sprint", source="unstop", prize_php=None,
                 url="https://unstop.com/o/cebu"),
            make(title="Cebu Sprint", source="devpost", prize_php=750_000,
                 url="https://cebu.devpost.com/"),
        ]
    )
    assert len(merged) == 1
    assert merged[0].source == "devpost"
    assert merged[0].prize_php == 750_000
    assert merged[0].also_seen_on == ["unstop"]


def test_a_source_never_lists_itself_as_also_seen_on():
    merged = dedupe(
        [
            make(title="Dup", source="devpost", prize_php=None, url="https://a.devpost.com/"),
            make(title="Dup", source="devpost", prize_php=100, url="https://b.devpost.com/"),
        ]
    )
    assert merged[0].also_seen_on == []


def test_shared_platform_hosts_do_not_collapse_unrelated_events():
    """Every Devpost event shares one hostname; host matching must skip those."""
    merged = dedupe(
        [
            make(title="Alpha Hack", url="https://devpost.com/one", source="devpost"),
            make(title="Beta Hack", url="https://devpost.com/two", source="devpost"),
        ]
    )
    assert len(merged) == 2


def test_dedicated_event_domains_still_merge():
    merged = dedupe(
        [
            make(title="Gamma Jam", url="https://gammajam.com/a", source="devpost"),
            make(title="Gamma Jam Manila", url="https://gammajam.com/b", source="devfolio"),
        ]
    )
    assert len(merged) == 1


def test_dedupe_preserves_input_order():
    items = [
        make(title="First", url="https://one.devpost.com/"),
        make(title="Second", url="https://two.devpost.com/"),
        make(title="Third", url="https://three.devpost.com/"),
    ]
    assert [h.title for h in dedupe(items)] == ["First", "Second", "Third"]
