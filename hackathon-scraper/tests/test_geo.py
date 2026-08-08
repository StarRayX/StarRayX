from __future__ import annotations

import pytest

from phhack.geo import (
    PH_TIER_GLOBAL,
    PH_TIER_LOCAL,
    PH_TIER_NONE,
    PH_TIER_SEASIA,
    classify,
    tier_rank,
)


@pytest.mark.parametrize(
    "text",
    [
        "Hack it UP — UP Manila",
        "eGovPH Hackathon 2026",
        "TECHATHLON, Cebu City",
        "Pinoy Coders Challenge",
        "Davao Agritech Sprint",
        "Ateneo Blue Hacks",
        "Hackathon hosted in the Philippines",
        "Fintech jam, Makati, PH",
    ],
)
def test_detects_philippine_listings(text):
    tier, _ = classify(text)
    assert tier == PH_TIER_LOCAL


@pytest.mark.parametrize(
    "text",
    [
        # Each of these hides a PH keyword inside an unrelated word; substring
        # matching used to classify them as Philippine.
        "Concrete Innovation Challenge, Berlin",
        "I trust this event, Tokyo",
        "Cupertino Robotics Meet",
    ],
)
def test_does_not_false_positive_on_substrings(text):
    tier, _ = classify(text)
    assert tier == PH_TIER_NONE


def test_regional_scope_ranks_below_local():
    tier, reason = classify("ASEAN Data Science Explorers")
    assert tier == PH_TIER_SEASIA
    assert "asean" in reason


def test_online_listings_are_globally_reachable():
    assert classify("Some Hack", is_online=True)[0] == PH_TIER_GLOBAL
    assert classify("Worldwide Virtual Buildathon")[0] == PH_TIER_GLOBAL


def test_unrelated_in_person_event_is_excluded():
    assert classify("Paris Blockchain Week Hack")[0] == PH_TIER_NONE


def test_reason_is_always_populated():
    for text, online in [("UP Manila", False), ("", True), ("Nothing", False)]:
        _, reason = classify(text, online)
        assert reason


def test_local_beats_online_flag():
    # An online Philippine event is still a Philippine event.
    assert classify("Manila Virtual Hack", is_online=True)[0] == PH_TIER_LOCAL


def test_tier_rank_orders_by_relevance():
    assert (
        tier_rank(PH_TIER_LOCAL)
        < tier_rank(PH_TIER_SEASIA)
        < tier_rank(PH_TIER_GLOBAL)
        < tier_rank(PH_TIER_NONE)
    )
