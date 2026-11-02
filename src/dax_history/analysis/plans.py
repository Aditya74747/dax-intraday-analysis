"""Buy-only investment plans on daily prices.

A budget is split into purchases with a fixed fee each and nothing is ever sold.
Money not yet invested is held as cash earning nothing, and every plan is valued
at the last close.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .metrics import cagr, compositions, max_drawdown, xirr, years_between

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
EVERY_N_DAYS = [1, 2, 3, 5, 10, 21, 63, 126, 252]
SPREAD_YEARS = [1, 2, 3, 5, 10]
DIP_CHUNKS = 20
DIP_GAP_DAYS = 21  # at least a month between dip purchases
DIP_LEVELS = [0.05, 0.10, 0.15, 0.20, 0.30]


@dataclass
class PlanResult:
    plan: str
    purchases: int
    fees: float
    final_value: float
    roi: float
    cagr: float
    money_weighted_cagr: float
    worst_drop: float
    path: pd.Series  # value of the whole budget (shares + cash) each day

    def row(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "path"}


class BuyOnly:
    def __init__(self, prices: pd.DataFrame, budget: float, fee: float):
        self.prices, self.budget, self.fee = prices, budget, fee
        self.close = prices["Close"].to_numpy()
        self.last = self.close[-1]
        self.start, self.end = prices.index[0], prices.index[-1]
        self.years = years_between(self.start, self.end)

    @property
    def days(self) -> pd.DatetimeIndex:
        return self.prices.index

    def month_starts(self) -> pd.DatetimeIndex:
        return self.days[~self.days.to_period("M").duplicated()]

    def run(self, plan: str, dates, price: str = "Open",
            amounts: np.ndarray | None = None) -> PlanResult:
        """Buy `amounts` (default: the budget split evenly) on `dates` at `price`."""
        dates = pd.DatetimeIndex(dates)
        if amounts is None:
            amounts = np.full(len(dates), self.budget / len(dates))
        amounts = np.asarray(amounts, float)
        units = np.maximum(amounts - self.fee, 0) / self.prices.loc[dates, price].to_numpy()

        positions = self.days.get_indexer(dates)
        bought = np.zeros(len(self.days))
        spent = np.zeros(len(self.days))
        np.add.at(bought, positions, units)
        np.add.at(spent, positions, amounts)
        path = bought.cumsum() * self.close + self.budget - spent.cumsum()

        value = path[-1]
        ages = np.array([years_between(d, self.end) for d in dates])
        return PlanResult(
            plan=plan,
            purchases=len(dates),
            fees=self.fee * len(dates),
            final_value=value,
            roi=value / self.budget - 1,
            cagr=cagr(value, self.budget, self.years),
            money_weighted_cagr=xirr(ages, amounts, units.sum() * self.last),
            worst_drop=max_drawdown(path),
            path=pd.Series(path, index=self.days),
        )


def table(results: list[PlanResult]) -> pd.DataFrame:
    rows = pd.DataFrame([r.row() for r in results]).set_index("plan")
    return rows.sort_values("final_value", ascending=False)


def frequency_plans(bt: BuyOnly) -> list[PlanResult]:
    """One purchase on day one versus equal purchases every N trading days."""
    results = [bt.run("all at once on day 1", bt.days[:1])]
    results += [bt.run(f"every {n} trading days" if n > 1 else "every trading day",
                       bt.days[::n]) for n in EVERY_N_DAYS]
    return results


def spread_plans(bt: BuyOnly) -> list[PlanResult]:
    """Equal monthly purchases during the first Y years, then just holding."""
    starts = bt.month_starts()
    results = [bt.run(f"monthly for the first {y} years" if y > 1 else "monthly for the first year",
                      starts[starts < bt.start + pd.DateOffset(years=y)])
               for y in SPREAD_YEARS]
    results.append(bt.run("monthly for the whole period", starts))
    return results


def calendar_plans(bt: BuyOnly) -> list[PlanResult]:
    """Does the weekday or the day of the month matter?"""
    days = bt.days
    months = days.to_period("M")
    nth = pd.Series(days, index=days).groupby(months).cumcount().to_numpy()
    results = [bt.run(f"every {name}", days[days.day_of_week == i])
               for i, name in enumerate(WEEKDAYS)]
    results += [bt.run(f"monthly on trading day {n + 1}", days[nth == n]) for n in (0, 4, 9, 14)]
    results.append(bt.run("monthly on the last trading day", days[~months.duplicated(keep="last")]))
    return results


def intraday_price_plans(bt: BuyOnly) -> list[PlanResult]:
    """Monthly purchases at the day's open, close, low (perfect) or high (worst)."""
    return [bt.run(f"monthly at the day's {label}", bt.month_starts(), price=column)
            for label, column in [("open", "Open"), ("close", "Close"),
                                  ("low (perfect timing)", "Low"),
                                  ("high (worst timing)", "High")]]


def dip_dates(prices: pd.DataFrame, level: float) -> pd.DatetimeIndex:
    """Next-day buy dates whenever the close is `level` or more below its running peak,
    at least DIP_GAP_DAYS apart and at most DIP_CHUNKS of them."""
    close = prices["Close"].to_numpy()
    peak = np.maximum.accumulate(close)
    picks, last_buy = [], -DIP_GAP_DAYS
    for i in range(len(close) - 1):
        if len(picks) == DIP_CHUNKS:
            break
        if close[i] <= (1 - level) * peak[i] and i - last_buy >= DIP_GAP_DAYS:
            picks.append(i + 1)
            last_buy = i
    return prices.index[picks]


def dip_plan(bt: BuyOnly, level: float) -> PlanResult:
    dates = dip_dates(bt.prices, level)
    return bt.run(f"buy {level:.0%}+ dips ({len(dates)}/{DIP_CHUNKS} chunks used)", dates,
                  amounts=np.full(len(dates), bt.budget / DIP_CHUNKS))


def dip_plans(bt: BuyOnly) -> list[PlanResult]:
    return [dip_plan(bt, level) for level in DIP_LEVELS]


def start_year_check(prices: pd.DataFrame, budget: float, fee: float,
                     step: int = 3) -> pd.DataFrame:
    """Rerun the main contenders from later start dates: is the winner stable?"""
    rows = []
    first, last = prices.index[0].year, prices.index[-1].year
    for year in range(first, last - 3, step):
        part = prices[prices.index >= pd.Timestamp(year, 1, 1)]
        bt = BuyOnly(part, budget, fee)
        starts = bt.month_starts()
        rows.append({
            "start": part.index[0].date(),
            "all at once": bt.run("", bt.days[:1]).final_value,
            "monthly, 1 year": bt.run("", starts[:12]).final_value,
            "monthly, 3 years": bt.run("", starts[:36]).final_value,
            "10% dips": dip_plan(bt, 0.10).final_value,
            "20% dips": dip_plan(bt, 0.20).final_value,
        })
    return pd.DataFrame(rows).set_index("start")


def exhaustive_splits(bt: BuyOnly, chunk: int = 1000,
                      step_years: int = 2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Score every split of the budget in `chunk`s across dates `step_years` apart.

    Returns the entry dates with their growth per euro, and every split ranked.
    """
    targets = [bt.start + pd.DateOffset(years=y) for y in range(0, int(bt.years) + 1, step_years)]
    anchors = bt.days[np.unique(bt.days.searchsorted(targets).clip(max=len(bt.days) - 1))]
    growth = bt.last / bt.prices.loc[anchors, "Open"].to_numpy()

    counts = compositions(int(bt.budget // chunk), len(anchors))
    values = ((counts * chunk - bt.fee * (counts > 0)) * growth).sum(axis=1)
    splits = pd.DataFrame({
        "split": [", ".join(f"€{c * chunk:,} on {d:%Y-%m-%d}" for d, c in zip(anchors, row) if c)
                  for row in counts],
        "purchases": (counts > 0).sum(axis=1),
        "final_value": values,
    })
    splits["cagr"] = (splits["final_value"] / bt.budget) ** (1 / bt.years) - 1
    entries = pd.DataFrame({"date": anchors.date, "growth_per_euro": growth})
    return entries, splits.sort_values("final_value", ascending=False, ignore_index=True)


def hindsight(bt: BuyOnly) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The cheapest day of each year, and the best single-purchase CAGR by holding time."""

    def outcome(day: pd.Timestamp) -> dict:
        low = bt.prices.loc[day, "Low"]
        value = (bt.budget - bt.fee) / low * bt.last
        return {"date": day.date(), "low": low, "final_value": value,
                "cagr": cagr(value, bt.budget, years_between(day, bt.end))}

    lows = bt.prices["Low"]
    yearly = pd.DataFrame([outcome(d) for d in lows.groupby(lows.index.year).idxmin()])

    held = np.array([years_between(d, bt.end) for d in bt.days])
    best = []
    for min_years in (1, 3, 5, 10):
        eligible = lows[held >= min_years]
        if eligible.empty:
            continue
        growth = (bt.budget - bt.fee) / eligible * bt.last / bt.budget
        rates = growth ** (1 / held[held >= min_years]) - 1
        held_label = f"{min_years} year{'s' if min_years > 1 else ''}"
        best.append({"held at least": held_label, **outcome(rates.idxmax())})
    return yearly, pd.DataFrame(best)


def calendar_stats(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Average close-to-close move by weekday and by calendar month, plus day ranges."""
    daily = prices["Close"].pct_change().dropna()
    by_day = daily.groupby(daily.index.day_of_week).agg(
        average="mean", share_up=lambda r: (r > 0).mean(), days="size")
    by_day.index = pd.Index(WEEKDAYS, name="weekday")

    monthly = prices["Close"].resample("ME").last().pct_change().dropna()
    by_month = monthly.groupby(monthly.index.month).agg(
        average="mean", share_up=lambda r: (r > 0).mean(), years="size")
    by_month.index = pd.Index(pd.to_datetime(by_month.index, format="%m").strftime("%B"),
                              name="month")

    ranges = {
        "high_above_low": (prices["High"] / prices["Low"] - 1).mean(),
        "open_above_low": (prices["Open"] / prices["Low"] - 1).mean(),
    }
    return by_day, by_month, ranges
