"""Hour-of-day analyses on hourly prices.

Round-trip strategies trade once per day: buy at the open of one hourly bar and
sell at the close of the same or a later bar, or hold overnight from the 17:30
close to the next 09:00 open. Each reinvests its gains daily.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .data import TRADING_HOURS
from .metrics import max_drawdown


def exit_time(bar_hour: int) -> str:
    # The 17:00 bar ends at the 17:30 close.
    return "17:30" if bar_hour == 17 else f"{bar_hour + 1:02d}:00"


def bars_by_day(hourly: pd.DataFrame, column: str) -> pd.DataFrame:
    """One row per trading day, one column per bar hour."""
    return hourly[column].groupby([hourly.index.normalize(), hourly.index.hour]).first().unstack()


def hour_stats(hourly: pd.DataFrame) -> pd.DataFrame:
    """Average move inside each hourly bar, from its open to its close."""
    moves = hourly["Close"] / hourly["Open"] - 1
    out = moves.groupby(hourly.index.hour).agg(
        average="mean", share_up=lambda r: (r > 0).mean(), bars="size")
    out.index = pd.Index([f"{h:02d}:00-{exit_time(h)}" for h in out.index], name="hour")
    return out


def round_trip_returns(hourly: pd.DataFrame) -> pd.DataFrame:
    """Daily return of each round-trip strategy; days with a missing bar count as 0."""
    opens, closes = bars_by_day(hourly, "Open"), bars_by_day(hourly, "Close")
    strategies = {}
    for entry in TRADING_HOURS:
        for exit_bar in TRADING_HOURS:
            if exit_bar >= entry and entry in opens and exit_bar in closes:
                strategies[f"{entry:02d}:00→{exit_time(exit_bar)}"] = closes[exit_bar] / opens[entry] - 1
    strategies["overnight 17:30→09:00"] = opens[9] / closes[17].shift(1) - 1
    return pd.DataFrame(strategies).fillna(0.0)


def strategy_table(returns: pd.DataFrame, cost: float, budget: float) -> pd.DataFrame:
    """Final value of `budget` in each strategy, after `cost` per round trip."""
    values = (1 + returns - cost).cumprod()
    daily = values.pct_change().fillna(values.iloc[0] - 1)
    out = pd.DataFrame({
        "final_value": values.iloc[-1] * budget,
        "return": values.iloc[-1] - 1,
        "sharpe": daily.mean() / daily.std() * np.sqrt(252),
        "worst_drop": values.apply(max_drawdown),
    })
    out.index.name = "strategy"
    return out.sort_values("final_value", ascending=False)


def hindsight_check(returns: pd.DataFrame, cost: float, budget: float) -> pd.DataFrame:
    """Rank strategies on the first half of the days, then see how they did on the second."""
    middle = len(returns) // 2
    first = strategy_table(returns.iloc[:middle], cost, budget)
    second = strategy_table(returns.iloc[middle:], cost, budget)
    out = pd.DataFrame({
        "first_half": first["return"],
        "second_half": second["return"].reindex(first.index),
        "first_half_rank": np.arange(1, len(first) + 1),
    })
    out["second_half_rank"] = second["return"].rank(ascending=False).astype(int).reindex(first.index)
    return out


def buy_hour_plans(hourly: pd.DataFrame, budget: float, fee: float) -> pd.DataFrame:
    """Buy-only: does the hour of the purchase matter? All at once on day one, or
    monthly over the period, always at the same hour, valued at the last close."""
    opens = bars_by_day(hourly, "Open")
    complete = opens.dropna()  # days with every bar, so no planned purchase is missing
    months = complete.index.to_period("M")
    monthly = complete[~months.duplicated()]
    last = hourly["Close"].iloc[-1]

    rows = []
    for hour in complete.columns:
        rows.append({
            "hour": f"{hour:02d}:00",
            "all at once on day 1": (budget - fee) / complete[hour].iloc[0] * last,
            f"{len(monthly)} monthly purchases":
                ((budget / len(monthly) - fee) / monthly[hour]).sum() * last,
        })
    return pd.DataFrame(rows).set_index("hour")
