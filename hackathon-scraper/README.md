# PH Hackathon Scraper

Finds hackathons a Philippine team can actually enter, and ranks them so the
**biggest prize pools come first**.

Aggregates five platforms, converts every prize into PHP so pots can be compared
across currencies, scores each listing, merges cross-posted duplicates, and
prints a table, JSON, CSV, or a Markdown digest.

```
#  PRIZE   SCORE  TIER    LEFT  TITLE                     SOURCE
-  ------  -----  ------  ----  ------------------------  -------
1  ₱58.0M  75     GLOBAL  49d   Global Agents Hack        devpost
     https://global-agents.devpost.com/
2  ₱1.4M   80     PH      28d   Bayanihan Build 2026      devpost
     https://bayanihan-build.devpost.com/
3  ₱750K   77     PH      19d   Cebu Fintech Sprint       devpost
     https://cebu-fintech.devpost.com/
```

## Install

```bash
cd hackathon-scraper
pip install -r requirements.txt      # just `requests`
```

Optionally `pip install -e .` to get a `phhack` command on your PATH. Otherwise
run it as `python -m phhack`.

## Usage

```bash
python -m phhack scan                              # everything, prize-ranked
python -m phhack scan --ph-only                    # Philippine events only
python -m phhack scan --min-prize 500000           # at least ₱500K
python -m phhack scan --sort deadline --limit 10   # what closes soonest
python -m phhack scan --format md --out digest.md  # Markdown digest
python -m phhack sources                           # what it scrapes
```

### Options worth knowing

| Flag | What it does |
|:--|:--|
| `--tiers local,seasia,global` | Relevance filter (see below). Default excludes `none`. |
| `--ph-only` | Shorthand for `--tiers local`. |
| `--min-prize PHP` | Drop listings below a PHP-converted threshold. |
| `--require-prize` | Also drop listings with no published prize. |
| `--sort prize\|score\|deadline` | Ordering. Default `prize`. |
| `--format table\|json\|csv\|md` | Output shape. |
| `--sources devpost,devfolio,...` | Narrow the sources. |
| `--no-global` | Skip the untargeted global sweep — faster, PH-focused. |
| `--fx-file fx.json` | Override exchange rates, e.g. `{"USD": 58.2}`. |
| `--dump-raw DIR` | Save raw API responses for debugging a parser. |
| `--strict` | Abort if any source fails instead of warning. |
| `-v` / `-vv` | Info / debug logging. |

## How ranking works

Prize size dominates, deliberately. The score is a 0–100 blend:

| Signal | Weight | Notes |
|:--|--:|:--|
| Prize | 62% | Log-scaled PHP value |
| Relevance | 23% | How reachable the event is from the Philippines |
| Urgency | 15% | Peaks ~30 days out; zero once closed |

The prize component is **log-scaled** on purpose. On a linear scale a single
₱50M crypto bounty would flatten every local event to approximately zero. Log
keeps a ₱500K Manila hackathon meaningfully ranked against a ₱5M global one
while still putting the bigger pot on top. It saturates at ₱5M.

`--sort prize` (the default) ignores the blend entirely and orders purely by
converted prize value. Use `--sort score` if you want deadline and locality
factored in.

**Unknown prizes are not zero.** A listing that hasn't published a prize yet
gets a middling prize component and survives `--min-prize`, because "not
announced" and "too small" are different things. Use `--require-prize` to drop
them.

### Relevance tiers

| Tier | Meaning |
|:--|:--|
| `local` | Explicitly Philippine — a PH city, university, organiser, or keyword |
| `seasia` | Regional events a PH team is eligible for (ASEAN, APAC, SEA) |
| `global` | Worldwide/online, joinable from Manila |
| `none` | Tied to somewhere else. Filtered out by default |

## Sources

| Source | Status | Notes |
|:--|:--|:--|
| Devpost | verified | Primary. Supports server-side sorting by prize amount |
| Devfolio | experimental | Strong Asia coverage |
| HackerEarth | experimental | Sponsored challenges, often large pools |
| DoraHacks | experimental | Web3 bounties — routinely the biggest pots |
| Unstop | experimental | INR-denominated; growing SEA section |

**"experimental" means the endpoint is undocumented and its schema was inferred,
not verified against a live response.** Those adapters read fields leniently and
fail soft: if a provider reshapes its payload you get a warning and fewer rows,
never a crash or a wrong number. The run summary on stderr always reports what
each source contributed:

```
412 fetched (devpost=180, devfolio=64, dorahacks=40) → 96 matched → 71 unique → 25 shown
  ! unstop: FetchError: https://unstop.com/... returned non-JSON
```

If a source returns nothing, `--dump-raw ./raw` writes the actual payloads so
you can fix the field names in `phhack/sources/<name>.py`.

## Adding a source

Subclass `Source`, parse into `Hackathon`, register it. Nothing else changes.

```python
# phhack/sources/mysite.py
class MySiteSource(Source):
    name = "mysite"
    label = "MySite"
    homepage = "https://mysite.com/hackathons"
    default_currency = "USD"

    def fetch(self, ctx):
        payload = ctx.http.get_json("https://mysite.com/api/events")
        return [
            make_hackathon(
                source=self.name,
                title=pick_str(r, "name", "title", default="") or "",
                url=absolute_url(pick_str(r, "url")),
                prize_text=pick_str(r, "prize", "prize_pool"),
                location_text=pick_str(r, "city", "location"),
            )
            for r in find_records(payload, ("events",))
        ]
```

Then add it to `ALL_SOURCES` in `phhack/sources/__init__.py`. Prize parsing,
currency conversion, PH classification, scoring, and de-duplication are all
handled by the pipeline — adapters only map fields.

Use the lenient helpers (`pick_str`, `find_records`, `names_of`,
`normalise_status`, `absolute_url`) rather than direct key access. They are what
makes drift survivable.

## Automated weekly digest

`.github/workflows/hackathon-digest.yml` runs the scraper every Monday and
commits `hackathon-scraper/data/digest.md` and `data/hackathons.json`. Trigger
it manually from the Actions tab, or delete the workflow if you'd rather run
locally.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

175 tests, fully offline — every source adapter is driven by fixtures through a
fake HTTP client, so the suite never touches the network. Coverage includes
prize-string edge cases (HTML-wrapped amounts, entity-encoded symbols, ranges,
`$1.5M` shorthand, Indian lakh grouping), PH false-positive traps, year-rollover
in date ranges, and a schema-drift matrix asserting every adapter degrades to an
empty list rather than raising.

## Caching

Responses cache to `~/.cache/phhack` for an hour. `--no-cache` bypasses it,
`--cache-ttl` changes the lifetime. Requests are paced at ~0.6s apart with
retry-and-backoff on 429/5xx.

## Limitations

- Many Philippine hackathons are announced only on Facebook or in university
  Discords and never reach an aggregator. This tool covers the platforms, not
  those channels.
- Exchange rates are a static table. Fine for ranking, not for accounting —
  override with `--fx-file` if it matters.
- Prizes are read from listing text, so "in prizes" totals and grand-prize
  figures aren't distinguished; the largest number found wins.
