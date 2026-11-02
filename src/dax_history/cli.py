"""Command-line interface for dax-history."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .fetch import DAX_TICKER, INTERVALS, earliest_start, fetch_history, is_intraday
from .storage import SUPPORTED_SUFFIXES, load, merge, save


def subtract_years(day: date, years: int) -> date:
    """Return the same calendar day `years` earlier (Feb 29 becomes Feb 28)."""
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a valid date: use YYYY-MM-DD."
        ) from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dax-history",
        description="Download daily or intraday DAX prices to CSV or Excel.",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("dax.csv"),
        help="output file ending in .csv or .xlsx (default: dax.csv)",
    )
    parser.add_argument(
        "-i", "--interval", choices=INTERVALS, default="1d",
        help="bar length (default: 1d); Yahoo keeps 1h bars for about 2 years, "
        "5m to 30m bars for 60 days and 1m bars for 30 days",
    )
    parser.add_argument(
        "--years", type=int, default=20,
        help="years of history to fetch when --start is not set (default: 20)",
    )
    parser.add_argument(
        "--start", type=parse_date, help="first date, YYYY-MM-DD (overrides --years)",
    )
    parser.add_argument(
        "--end", type=parse_date, help="last date, YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--append", action="store_true",
        help="merge into the existing output file instead of replacing it",
    )
    parser.add_argument(
        "--ticker", default=DAX_TICKER,
        help=f"Yahoo Finance ticker (default: {DAX_TICKER})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.output.suffix.lower() not in SUPPORTED_SUFFIXES:
        parser.error("--output must end in .csv or .xlsx")
    if args.years < 1:
        parser.error("--years must be at least 1")

    today = date.today()
    end = args.end or today
    start = args.start or subtract_years(end, args.years)
    if start > end:
        parser.error("the start date must not be after the end date")

    earliest = earliest_start(args.interval, today)
    if earliest is not None and start < earliest:
        if end < earliest:
            parser.error(
                f"Yahoo only keeps {args.interval} data back to {earliest}; "
                "use a later --end or --interval 1d"
            )
        print(
            f"Note: Yahoo only keeps {args.interval} data back to {earliest}, "
            f"so the download starts there instead of {start}.",
            file=sys.stderr,
        )
        start = earliest

    try:
        data = fetch_history(args.ticker, start, end, args.interval)
        if args.append and args.output.exists():
            data = merge(load(args.output), data)
        save(data, args.output)
    except (RuntimeError, OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    if is_intraday(args.interval):
        first, last = (t.strftime("%Y-%m-%d %H:%M") for t in data.index[[0, -1]])
        unit = f"{args.interval} bars"
    else:
        first, last = (t.date() for t in data.index[[0, -1]])
        unit = "trading days"
    print(f"Saved {len(data)} {unit} ({first} to {last}) to {args.output}")
    return 0
