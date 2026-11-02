"""Run every analysis and write results/REPORT.md with its charts."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Callable

import pandas as pd

from .. import fetch, storage
from . import charts, intraday, plans, random_plans
from .data import DAILY_FILE, DAILY_START, HOURLY_FILE, load_daily, load_hourly

SELL_OFFS = {
    "Euro crisis": ("2011-07-01", "2011-12-31"),
    "China sell-off": ("2015-08-01", "2016-03-31"),
    "Covid crash": ("2020-02-15", "2020-04-30"),
    "Inflation & war": ("2022-01-01", "2022-12-31"),
    "Tariff shock": ("2025-03-15", "2025-04-30"),
}


def euros(x: float) -> str:
    return f"€{x:,.0f}"


def signed(x: float) -> str:
    return f"{x:+.1%}"


def share(x: float) -> str:
    return f"{x:.0%}"


PLAN_FORMATS = {"fees": euros, "final_value": euros, "roi": signed, "cagr": signed,
                "money_weighted_cagr": signed, "worst_drop": signed}
HEADERS = {"final_value": "final value", "roi": "total return", "cagr": "CAGR",
           "money_weighted_cagr": "money-weighted CAGR", "worst_drop": "worst drop",
           "share_up": "share up", "first_half": "first half", "second_half": "second half",
           "first_half_rank": "rank (first half)", "second_half_rank": "rank (second half)",
           "growth_per_euro": "€1 became", "years_waited": "years waited",
           "sharpe": "Sharpe ratio"}


def markdown(df: pd.DataFrame, formats: dict[str, Callable] | None = None,
             index: bool = True) -> str:
    """Render a DataFrame as a GitHub table, numbers right-aligned."""
    formats = formats or {}
    frame = df.reset_index() if index else df
    columns = list(frame.columns)
    numeric = [pd.api.types.is_numeric_dtype(frame[c]) for c in columns]
    lines = ["| " + " | ".join(HEADERS.get(str(c), str(c)) for c in columns) + " |",
             "| " + " | ".join("---:" if n else "---" for n in numeric) + " |"]
    for _, row in frame.iterrows():
        cells = [formats[c](v) if c in formats else
                 (f"{v:,}" if isinstance(v, int) else str(v)) for c, v in row.items()]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def download(daily_file: Path, hourly_file: Path) -> None:
    """Fetch daily prices since DAILY_START and append the latest hourly bars."""
    today = date.today()
    daily = fetch.fetch_history(fetch.DAX_TICKER, date.fromisoformat(DAILY_START), today, "1d")
    storage.save(daily, daily_file)
    print(f"Saved {len(daily):,} daily rows to {daily_file}")

    hourly = fetch.fetch_history(fetch.DAX_TICKER, fetch.earliest_start("1h", today), today, "1h")
    if hourly_file.exists():
        hourly = storage.merge(storage.load(hourly_file), hourly)
    storage.save(hourly, hourly_file)
    print(f"Saved {len(hourly):,} hourly rows to {hourly_file}")


def daily_section(prices: pd.DataFrame, args: argparse.Namespace, out: Path) -> list[str]:
    bt = plans.BuyOnly(prices, args.budget, args.fee)
    chart_dir = out / "charts"
    lines = [
        f"## Part 1 – Daily prices, {bt.start:%d %b %Y} to {bt.end:%d %b %Y}",
        "",
        f"{len(prices):,} trading days ({bt.years:.1f} years). The DAX went from "
        f"{prices['Open'].iloc[0]:,.0f} at the first open to {bt.last:,.0f} at the last close.",
        f"Every plan invests a budget of {euros(args.budget)}, pays a {euros(args.fee)} fee per "
        "purchase, buys at the day's open unless stated otherwise and never sells. Money not "
        "yet invested waits as cash earning nothing.",
        "",
        "- **CAGR**: yearly growth of the whole budget, counted from the first day.",
        "- **Money-weighted CAGR**: yearly growth of the money while it was actually invested "
        "(internal rate of return). It flatters plans that invest late, because it ignores "
        "the years the cash sat idle.",
        "- **Worst drop**: largest fall of the whole budget (shares + cash) from a previous peak.",
        "",
        f"![DAX price history](charts/{charts.price_history(prices, SELL_OFFS, chart_dir / 'dax_price.png').name})",
        "",
    ]

    frequency_results = plans.frequency_plans(bt)
    lump = frequency_results[0]
    frequency = plans.table(frequency_results)
    lines += ["### 1.1 How often to buy", "",
              "The budget split into equal purchases every N trading days across the whole period.", "",
              markdown(frequency, PLAN_FORMATS), "",
              f"![Fees by purchase frequency](charts/"
              f"{charts.fees_by_frequency(frequency, args.budget, chart_dir / 'fees_by_frequency.png').name})", ""]

    spread_results = plans.spread_plans(bt)
    by_name = {r.plan: r for r in spread_results}
    paths = {"All at once on day 1": lump.path,
             "Monthly for the first 3 years": by_name["monthly for the first 3 years"].path,
             "Monthly for the whole period": by_name["monthly for the whole period"].path}
    lines += ["### 1.2 How long to spread the purchases", "",
              "Equal monthly purchases during the first Y years, then holding.", "",
              markdown(plans.table([lump, *spread_results]), PLAN_FORMATS), "",
              f"![Plan values over time](charts/{charts.plan_paths(paths, chart_dir / 'plan_paths.png').name})", ""]

    lines += ["### 1.3 Which day of the week or month", "",
              markdown(plans.table(plans.calendar_plans(bt)), PLAN_FORMATS), "",
              "### 1.4 Where in the day the purchase happens", "",
              "Monthly purchases at the day's open, close, low or high. Buying at the low "
              "every time is impossible in practice; it shows the most that intraday timing could add.", "",
              markdown(plans.table(plans.intraday_price_plans(bt)), PLAN_FORMATS), "",
              "### 1.5 Buying the dips", "",
              f"The budget is split into {plans.DIP_CHUNKS} equal chunks. One chunk is bought at "
              "the next open whenever the DAX closes the given percentage below its highest close so "
              f"far, at most once every {plans.DIP_GAP_DAYS} trading days. Unused chunks stay in cash.", "",
              markdown(plans.table(plans.dip_plans(bt)), PLAN_FORMATS), ""]

    check = plans.start_year_check(prices, args.budget, args.fee)
    lines += ["### 1.6 Does the winner depend on the start date?", "",
              "The main plans rerun from later start dates; final value today.", "",
              markdown(check, {c: euros for c in check.columns}), ""]

    entries, splits = plans.exhaustive_splits(bt)
    lines += ["### 1.7 Exhaustive search over split budgets", "",
              f"Every one of the {len(splits):,} ways to split {euros(args.budget)} into €1,000 "
              f"chunks across {len(entries)} entry dates two years apart.", "",
              markdown(entries, {"growth_per_euro": lambda g: f"€{g:.2f}"}, index=False), "",
              "Best 5 and worst 3 splits:", "",
              markdown(pd.concat([splits.head(5), splits.tail(3)]),
                       {"final_value": euros, "cagr": signed}, index=False), ""]

    simulation = random_plans.simulate(bt, args.plans, args.max_parts, args.min_part, args.seed)
    table = simulation.plans
    best_plans = table["final_value"].nlargest(5)
    lines += ["### 1.8 Random plans (Monte Carlo)", "",
              f"{len(table):,} random plans. Each splits {euros(args.budget)} into 1 to "
              f"{args.max_parts} whole-euro parts of random size (at least {euros(args.min_part)} each) "
              "and buys each part on a random trading day.", "",
              markdown(random_plans.percentiles(table["final_value"]), {"final_value": euros}), "",
              f"**{(table['final_value'] > lump.final_value).mean():.2%} of random plans beat putting "
              f"everything in on day 1 ({euros(lump.final_value)}).** The best five:", ""]
    lines += [f"{rank}. {euros(value)} – {random_plans.describe(simulation, i)}"
              for rank, (i, value) in enumerate(best_plans.items(), 1)]
    waited_bins = [-0.01, 1, 2, 4, 6, 8, 10, 12, 100]
    waited_labels = ["under 1", "1–2", "2–4", "4–6", "6–8", "8–10", "10–12", "12+"]
    group_formats = {"plans": lambda n: f"{n:,}", "median": euros, "best": euros,
                     "worst": euros, "beat benchmark": lambda x: f"{x:.1%}"}
    lines += ["", "Grouped by how long the money waited in cash on average (years):", "",
              markdown(random_plans.grouped(table, "years_waited", waited_bins, waited_labels,
                                            lump.final_value), group_formats), "",
              "Grouped by number of parts:", "",
              markdown(random_plans.grouped(table, "parts", [0, 1, 5, 10, 25, 50, 100],
                                            ["1", "2–5", "6–10", "11–25", "26–50", "51–100"],
                                            lump.final_value), group_formats), "",
              f"![Random plans](charts/"
              f"{charts.random_plans(table, lump.final_value, chart_dir / 'random_plans.png').name})", ""]

    yearly, best = plans.hindsight(bt)
    hindsight_formats = {"low": lambda x: f"{x:,.0f}", "final_value": euros, "cagr": signed}
    lines += ["### 1.9 Perfect hindsight", "",
              "The whole budget bought at the cheapest point of each year (the day's low). "
              "Nobody can do this in advance; it shows where the opportunities were.", "",
              markdown(yearly, hindsight_formats, index=False), "",
              "Highest CAGR from a single purchase, by minimum holding time:", "",
              markdown(best, hindsight_formats, index=False), ""]

    by_day, by_month, ranges = plans.calendar_stats(prices)
    calendar_formats = {"average": lambda x: f"{x:+.3%}", "share_up": lambda x: f"{x:.1%}"}
    lines += ["### 1.10 Calendar patterns", "",
              "Average close-to-close move by weekday:", "",
              markdown(by_day, calendar_formats), "",
              "Average monthly move by calendar month:", "",
              markdown(by_month, {"average": lambda x: f"{x:+.2%}", "share_up": share}), "",
              f"On an average day the high is {ranges['high_above_low']:.2%} above the low, and the "
              f"open is {ranges['open_above_low']:.2%} above the low.", ""]
    return lines


def hourly_section(hourly: pd.DataFrame, args: argparse.Namespace, out: Path) -> list[str]:
    chart_dir = out / "charts"
    days = hourly.index.normalize().nunique()
    stats = intraday.hour_stats(hourly)
    returns = intraday.round_trip_returns(hourly)
    strategy_formats = {"final_value": euros, "return": signed,
                        "sharpe": lambda x: f"{x:.2f}", "worst_drop": signed}
    no_cost = intraday.strategy_table(returns, 0.0, args.budget)
    with_cost = intraday.strategy_table(returns, args.round_trip_cost, args.budget)
    check = intraday.hindsight_check(returns, 0.0, args.budget)
    buy_hours = intraday.buy_hour_plans(hourly, args.budget, args.fee)

    lines = [
        f"## Part 2 – Hourly prices, {hourly.index[0]:%d %b %Y} to {hourly.index[-1]:%d %b %Y}",
        "",
        f"{len(hourly):,} hourly bars over {days} trading days, in Frankfurt time. "
        "Yahoo Finance keeps hourly DAX data for about two years only.",
        "",
        "### 2.1 Which hour of the day moves the market", "",
        markdown(stats, {"average": lambda x: f"{x:+.3%}", "share_up": share}), "",
        f"![Average move per hour](charts/{charts.hour_moves(stats, chart_dir / 'hour_moves.png').name})", "",
        "### 2.2 Trading the same hours every day", "",
        f"{len(returns.columns)} strategies, each starting with {euros(args.budget)} and "
        "reinvesting daily. Top 10 before costs:", "",
        markdown(no_cost.head(10), strategy_formats), "",
        f"The same top 10 after a trading cost of {args.round_trip_cost:.2%} per round trip "
        "(each strategy trades every day):", "",
        markdown(with_cost.loc[no_cost.index[:10]], strategy_formats), "",
        "### 2.3 Did the winners keep winning?", "",
        "Strategies ranked on the first half of the days, then tested on the second half.", "",
        markdown(check.head(10), {"first_half": signed, "second_half": signed}), "",
        f"![Hindsight check](charts/{charts.hindsight_scatter(check, chart_dir / 'hindsight_check.png').name})", "",
        "### 2.4 Does the hour of a long-term purchase matter?", "",
        f"Buy-only with {euros(args.budget)} and a {euros(args.fee)} fee per purchase, always "
        "at the same hour, valued at the last close.", "",
        markdown(buy_hours, {c: euros for c in buy_hours.columns}), "",
    ]
    return lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dax-report", description="Run every DAX analysis and write a Markdown report.")
    parser.add_argument("--download", action="store_true",
                        help="fetch fresh daily and hourly data before the analysis")
    parser.add_argument("--daily", type=Path, default=DAILY_FILE,
                        help=f"daily price file (default: {DAILY_FILE})")
    parser.add_argument("--hourly", type=Path, default=HOURLY_FILE,
                        help=f"hourly price file (default: {HOURLY_FILE})")
    parser.add_argument("--out", type=Path, default=Path("results"),
                        help="folder for REPORT.md and charts (default: results)")
    parser.add_argument("--budget", type=int, default=10_000, help="euros to invest (default: 10000)")
    parser.add_argument("--fee", type=float, default=1, help="fee per purchase in euros (default: 1)")
    parser.add_argument("--round-trip-cost", type=float, default=0.0005,
                        help="cost of one buy+sell as a fraction, for hourly trading (default: 0.0005)")
    parser.add_argument("--plans", type=int, default=200_000, help="random plans (default: 200000)")
    parser.add_argument("--max-parts", type=int, default=100,
                        help="most purchases in a random plan (default: 100)")
    parser.add_argument("--min-part", type=int, default=50,
                        help="smallest purchase in a random plan, euros (default: 50)")
    parser.add_argument("--seed", type=int, default=1, help="random seed (default: 1)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_parts * args.min_part > args.budget:
        parser.error("--max-parts times --min-part must not exceed --budget")

    try:
        if args.download:
            download(args.daily, args.hourly)
        daily = load_daily(args.daily)
        hourly = load_hourly(args.hourly)
    except (RuntimeError, OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        print("Download the data first with: uv run dax-report --download", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    lines = [
        "# DAX investing study – full results",
        "",
        f"Generated on {date.today():%d %B %Y} by `dax-report`. Data: Yahoo Finance, ticker "
        f"`{fetch.DAX_TICKER}`. Past results do not predict future returns; this is not "
        "financial advice.",
        "",
    ]
    lines += daily_section(daily, args, args.out)
    lines += hourly_section(hourly, args, args.out)
    report = args.out / "REPORT.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {report} and {len(list((args.out / 'charts').glob('*.png')))} charts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
