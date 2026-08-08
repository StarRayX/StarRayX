"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import List, Optional, Sequence

from . import output
from .geo import PH_TIER_GLOBAL, PH_TIER_LOCAL, PH_TIER_NONE, PH_TIER_SEASIA
from .http import HttpClient
from .models import STATUS_ENDED, STATUS_OPEN, STATUS_UPCOMING
from .money import load_rates
from .pipeline import run
from .sources import (
    ALL_SOURCES,
    DEFAULT_QUERIES,
    DEFAULT_SOURCE_NAMES,
    FetchContext,
    resolve,
)

DEFAULT_CACHE_DIR = os.path.join(
    os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "phhack"
)

ALL_TIERS = (PH_TIER_LOCAL, PH_TIER_SEASIA, PH_TIER_GLOBAL, PH_TIER_NONE)
ALL_STATUSES = (STATUS_OPEN, STATUS_UPCOMING, STATUS_ENDED)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phhack",
        description=(
            "Find hackathons open to Philippine teams, ranked by prize pool."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  phhack scan\n"
            "  phhack scan --min-prize 500000 --limit 15\n"
            "  phhack scan --tiers local --sort deadline\n"
            "  phhack scan --format md --out digest.md\n"
            "  phhack sources\n"
        ),
    )
    sub = parser.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="fetch and rank hackathons")
    _add_scan_arguments(scan)

    sub.add_parser("sources", help="list available sources")

    # Bare `phhack` behaves like `phhack scan`, which is what you want 95% of
    # the time; the subparser still needs its defaults registered.
    _add_scan_arguments(parser, hidden=True)
    return parser


def _add_scan_arguments(parser: argparse.ArgumentParser, hidden: bool = False) -> None:
    def helptext(text: str) -> str:
        return argparse.SUPPRESS if hidden else text

    selection = parser.add_argument_group("selection")
    selection.add_argument(
        "--sources",
        default=",".join(DEFAULT_SOURCE_NAMES),
        help=helptext("comma-separated source names (default: all)"),
    )
    selection.add_argument(
        "--queries",
        default=",".join(DEFAULT_QUERIES),
        help=helptext("comma-separated search terms for text-search sources"),
    )
    selection.add_argument(
        "--tiers",
        default="local,seasia,global",
        help=helptext(
            "relevance tiers to keep: local, seasia, global, none "
            "(default: local,seasia,global)"
        ),
    )
    selection.add_argument(
        "--status",
        default="open,upcoming",
        help=helptext("open, upcoming, ended (default: open,upcoming)"),
    )
    selection.add_argument(
        "--ph-only",
        action="store_true",
        help=helptext("shorthand for --tiers local"),
    )
    selection.add_argument(
        "--no-global",
        action="store_true",
        help=helptext("skip the untargeted global sweep (faster, PH-focused)"),
    )

    prize = parser.add_argument_group("prize")
    prize.add_argument(
        "--min-prize",
        type=float,
        default=0.0,
        metavar="PHP",
        help=helptext("drop listings whose prize converts to less than this"),
    )
    prize.add_argument(
        "--require-prize",
        action="store_true",
        help=helptext("drop listings with no published prize"),
    )
    prize.add_argument(
        "--fx-file",
        metavar="PATH",
        help=helptext('JSON of PHP rates, e.g. {"USD": 58.2}, merged over defaults'),
    )

    shape = parser.add_argument_group("output")
    shape.add_argument(
        "--sort",
        choices=("prize", "score", "deadline"),
        default="prize",
        help=helptext("ordering (default: prize)"),
    )
    shape.add_argument("--limit", type=int, default=25, help=helptext("max rows (0 = all)"))
    shape.add_argument(
        "--format", choices=output.FORMATS, default="table", help=helptext("output format")
    )
    shape.add_argument("--out", metavar="PATH", help=helptext("write to a file instead of stdout"))

    net = parser.add_argument_group("network")
    net.add_argument("--max-pages", type=int, default=3, help=helptext("pages per query per source"))
    net.add_argument("--timeout", type=float, default=20.0, help=helptext("per-request timeout"))
    net.add_argument("--retries", type=int, default=3, help=helptext("retries per request"))
    net.add_argument("--delay", type=float, default=0.6, help=helptext("seconds between requests"))
    net.add_argument("--no-cache", action="store_true", help=helptext("bypass the on-disk cache"))
    net.add_argument("--cache-ttl", type=int, default=3600, help=helptext("cache lifetime, seconds"))
    net.add_argument(
        "--dump-raw",
        metavar="DIR",
        help=helptext("save raw responses here, for diagnosing a drifted parser"),
    )
    net.add_argument(
        "--strict",
        action="store_true",
        help=helptext("abort if any source fails (default: warn and continue)"),
    )

    parser.add_argument("-v", "--verbose", action="count", default=0, help=helptext("-v info, -vv debug"))
    parser.add_argument("-q", "--quiet", action="store_true", help=helptext("suppress the run summary"))


def _split(value: str) -> List[str]:
    return [part.strip().lower() for part in (value or "").split(",") if part.strip()]


def _validate(values: Sequence[str], allowed: Sequence[str], label: str) -> set:
    unknown = [v for v in values if v not in allowed]
    if unknown:
        raise SystemExit(
            f"error: unknown {label}: {', '.join(unknown)} "
            f"(choose from {', '.join(allowed)})"
        )
    return set(values)


def cmd_sources() -> int:
    print(f"{'NAME':<14}{'STATUS':<16}{'CURRENCY':<10}HOMEPAGE")
    print("-" * 78)
    for source in ALL_SOURCES:
        status = "experimental" if source.experimental else "verified"
        print(f"{source.name:<14}{status:<16}{source.default_currency:<10}{source.homepage}")
    print(
        "\n'experimental' means the endpoint is undocumented and its schema is "
        "inferred.\nThose adapters fail soft — run with --dump-raw to inspect a "
        "live payload."
    )
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    tiers = _validate(_split(args.tiers), ALL_TIERS, "tier")
    if args.ph_only:
        tiers = {PH_TIER_LOCAL}
    statuses = _validate(_split(args.status), ALL_STATUSES, "status")

    try:
        sources = resolve(_split(args.sources))
    except KeyError as exc:
        raise SystemExit(f"error: {exc}") from exc
    if not sources:
        raise SystemExit("error: no sources selected")

    try:
        rates = load_rates(args.fx_file)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"error: could not read --fx-file: {exc}") from exc

    client = HttpClient(
        timeout=args.timeout,
        retries=args.retries,
        delay=args.delay,
        cache_dir=None if args.no_cache else DEFAULT_CACHE_DIR,
        cache_ttl=args.cache_ttl,
        dump_dir=args.dump_raw,
    )

    ctx = FetchContext(
        http=client,
        queries=_split(args.queries) or list(DEFAULT_QUERIES),
        include_global=not args.no_global,
        max_pages=max(1, args.max_pages),
        statuses=statuses,
    )

    listings, report = run(
        sources=sources,
        ctx=ctx,
        tiers=tiers,
        statuses=statuses,
        min_prize_php=args.min_prize,
        require_prize=args.require_prize,
        sort_mode=args.sort,
        limit=None if args.limit == 0 else args.limit,
        rates=rates,
        strict=args.strict,
    )

    text = output.render(args.format, listings)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text if text.endswith("\n") else text + "\n")
        if not args.quiet:
            print(f"Wrote {len(listings)} listing(s) to {args.out}", file=sys.stderr)
    else:
        print(text)

    if not args.quiet:
        _print_summary(report, len(listings))

    # Every source failing is a real failure, not an empty result set.
    if report.errors and not report.fetched:
        return 1
    return 0


def _print_summary(report, shown: int) -> None:
    parts = [f"{name}={count}" for name, count in sorted(report.fetched.items())]
    print(
        f"\n{report.total_raw} fetched ({', '.join(parts) or 'none'}) → "
        f"{report.after_filter} matched → {report.after_dedupe} unique → {shown} shown",
        file=sys.stderr,
    )
    for name, message in sorted(report.errors.items()):
        print(f"  ! {name}: {message}", file=sys.stderr)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")

    if args.command == "sources":
        return cmd_sources()
    return cmd_scan(args)


if __name__ == "__main__":
    raise SystemExit(main())
