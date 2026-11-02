"""Monte Carlo search over random buy-only plans.

Each plan splits the budget into a random number of whole-euro parts of random
size and buys each part at the open of a random trading day, then holds.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .metrics import random_amounts
from .plans import BuyOnly


@dataclass
class MonteCarlo:
    plans: pd.DataFrame  # one row per plan: parts, final_value, cagr, timing measures
    amounts: list[np.ndarray]  # per plan: the euro amount of each purchase
    dates: list[pd.DatetimeIndex]  # per plan: the date of each purchase


def simulate(bt: BuyOnly, plans: int, max_parts: int, min_part: int,
             seed: int) -> MonteCarlo:
    """Run `plans` random plans, spread evenly over 1 to `max_parts` purchases."""
    budget = int(bt.budget)
    rng = np.random.default_rng(seed)
    growth = bt.last / bt.prices["Open"].to_numpy()  # value now of 1 euro bought at each open
    waited = ((bt.days - bt.start).days / 365.25).to_numpy()

    per_size = max(plans // max_parts, 1)
    frames, all_amounts, all_dates = [], [], []
    for parts in range(1, max_parts + 1):
        amounts = random_amounts(rng, per_size, parts, budget, min_part)
        picks = np.sort(rng.integers(0, len(bt.days), size=(per_size, parts)), axis=1)
        frames.append(pd.DataFrame({
            "parts": parts,
            "final_value": ((amounts - bt.fee) * growth[picks]).sum(axis=1),
            "years_waited": (amounts * waited[picks]).sum(axis=1) / budget,
            "share_in_first_2y": (amounts * (waited[picks] < 2)).sum(axis=1) / budget,
        }))
        all_amounts += list(amounts)
        all_dates += [bt.days[row] for row in picks]

    table = pd.concat(frames, ignore_index=True)
    table["cagr"] = (table["final_value"] / bt.budget) ** (1 / bt.years) - 1
    return MonteCarlo(table, all_amounts, all_dates)


def describe(result: MonteCarlo, index: int, limit: int = 5) -> str:
    buys = [f"€{a:,} on {d:%Y-%m-%d}"
            for a, d in zip(result.amounts[index], result.dates[index])]
    more = f", … {len(buys) - limit} more" if len(buys) > limit else ""
    return ", ".join(buys[:limit]) + more


def percentiles(values: pd.Series) -> pd.DataFrame:
    points = {"worst": 0.0, "5th percentile": 0.05, "25th percentile": 0.25,
              "median": 0.5, "75th percentile": 0.75, "95th percentile": 0.95, "best": 1.0}
    out = pd.DataFrame({"final_value": {k: values.quantile(q) for k, q in points.items()}})
    out.index.name = "outcome"
    return out


def grouped(plans: pd.DataFrame, column: str, bins: list[float], labels: list[str],
            benchmark: float) -> pd.DataFrame:
    """Final-value spread of the plans, grouped by one of their timing measures."""
    groups = plans.groupby(pd.cut(plans[column], bins, labels=labels), observed=True)["final_value"]
    out = groups.agg(plans="size", median="median", best="max", worst="min")
    out["beat benchmark"] = groups.apply(lambda v: (v > benchmark).mean())
    return out
