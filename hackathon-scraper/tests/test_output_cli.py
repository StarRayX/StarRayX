from __future__ import annotations

import csv
import io
import json
from datetime import date

import pytest

from conftest import TODAY, make

from phhack import output
from phhack.cli import main


@pytest.fixture
def rows():
    return [
        make(
            title="Global Agents Hack", url="https://global-agents.devpost.com/",
            source="devpost", prize_php=58_000_000, prize_amount=1_000_000,
            prize_currency="USD", ph_tier="global", score=91.4,
            starts_on=date(2026, 1, 15), ends_on=date(2026, 4, 10),
            themes=["AI"], also_seen_on=["devfolio"],
        ),
        make(
            title="Cebu Fintech | Sprint", url="https://cebu-fintech.devpost.com/",
            source="devpost", prize_php=750_000, ph_tier="local", score=70.2,
            ends_on=date(2026, 3, 11),
        ),
        make(title="No Prize Hack", url="https://quiet.devpost.com/", ph_tier="global", score=20.0),
    ]


def test_table_lists_every_row_with_its_url(rows):
    text = output.render("table", rows, TODAY)
    for item in rows:
        assert item.title in text
        assert item.url in text
    assert "₱58.0M" in text


def test_table_reports_days_remaining(rows):
    text = output.render("table", rows, TODAY)
    assert "19d" in text  # 2026-03-11 is 19 days after 2026-02-20
    assert "—" in text  # undated row


def test_table_handles_an_empty_result_set():
    assert "No hackathons matched" in output.render("table", [], TODAY)


def test_json_round_trips_and_serialises_dates(rows):
    payload = json.loads(output.render("json", rows, TODAY))

    assert payload["count"] == 3
    assert payload["generated_on"] == "2026-02-20"
    first = payload["hackathons"][0]
    assert first["starts_on"] == "2026-01-15"
    assert first["prize_currency"] == "USD"
    assert first["also_seen_on"] == ["devfolio"]
    assert payload["hackathons"][2]["ends_on"] is None


def test_csv_has_a_header_and_one_row_each(rows):
    parsed = list(csv.DictReader(io.StringIO(output.render("csv", rows, TODAY))))

    assert len(parsed) == 3
    assert parsed[0]["title"] == "Global Agents Hack"
    assert parsed[0]["prize_currency"] == "USD"
    assert parsed[0]["themes"] == "AI"
    assert parsed[0]["also_seen_on"] == "devfolio"


def test_markdown_escapes_pipes_so_the_table_survives(rows):
    text = output.render("md", rows, TODAY)
    assert r"Cebu Fintech \| Sprint" in text
    assert "[Global Agents Hack](https://global-agents.devpost.com/)" in text
    assert text.count("\n|") >= 4  # header, separator, three rows


def test_markdown_handles_an_empty_result_set():
    assert "No hackathons matched" in output.render("md", [], TODAY)


def test_unknown_format_is_rejected(rows):
    with pytest.raises(ValueError):
        output.render("pdf", rows, TODAY)


# --- CLI ---------------------------------------------------------------


def test_sources_command_lists_all_adapters(capsys):
    assert main(["sources"]) == 0
    out = capsys.readouterr().out
    for name in ("devpost", "devfolio", "hackerearth", "dorahacks", "unstop"):
        assert name in out
    assert "experimental" in out


def test_unknown_source_exits_with_a_helpful_message(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--sources", "myspace"])
    assert "unknown source" in str(exc.value)


def test_unknown_tier_is_rejected():
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--tiers", "mars"])
    assert "unknown tier" in str(exc.value)


def test_unknown_status_is_rejected():
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--status", "maybe"])
    assert "unknown status" in str(exc.value)


def test_missing_fx_file_is_reported_not_traced():
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--fx-file", "/nonexistent/fx.json"])
    assert "--fx-file" in str(exc.value)


def test_all_sources_failing_is_a_nonzero_exit(monkeypatch, capsys):
    """No network in CI, so every adapter fails — that must surface as exit 1."""
    from phhack.http import FetchError, HttpClient

    def explode(*args, **kwargs):
        raise FetchError("no network")

    for method in ("get_json", "post_json", "get_text"):
        monkeypatch.setattr(HttpClient, method, explode)

    assert main(["scan", "--no-cache", "--retries", "0"]) == 1
    assert "no network" in capsys.readouterr().err
