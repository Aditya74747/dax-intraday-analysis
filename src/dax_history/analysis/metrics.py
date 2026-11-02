"""Shared maths for the backtests: time, growth rates, drawdowns and budget splits."""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

SECONDS_PER_YEAR = 365.25 * 24 * 3600


def years_between(start: pd.Timestamp, end: pd.Timestamp) -> float:
    return (end - start).total_seconds() / SECONDS_PER_YEAR


def cagr(final: float, initial: float, years: float) -> float:
    """Compound annual growth rate turning `initial` into `final` over `years`."""
    return (final / initial) ** (1 / years) - 1


def xirr(ages: np.ndarray, amounts: np.ndarray, value: float) -> float:
    """Money-weighted yearly return: the rate at which each amount, invested
    `ages` years before the end, grows into `value` in total."""
    ages, amounts = np.asarray(ages, float), np.asarray(amounts, float)

    def excess(rate: float) -> float:
        return (amounts * (1 + rate) ** ages).sum() - value

    low, high = -0.99, 100.0
    for _ in range(200):
        mid = (low + high) / 2
        low, high = (mid, high) if excess(mid) < 0 else (low, mid)
    return (low + high) / 2


def max_drawdown(path: np.ndarray) -> float:
    """Largest fall from a running peak, as a negative fraction."""
    path = np.asarray(path, float)
    return (path / np.maximum.accumulate(path) - 1).min()


def compositions(total: int, parts: int) -> np.ndarray:
    """Every way to share `total` whole units between `parts` slots (zeros allowed).

    One row per way, e.g. compositions(2, 2) -> [[0, 2], [1, 1], [2, 0]].
    """
    bars = np.array(list(itertools.combinations(range(total + parts - 1), parts - 1)))
    bars = bars.reshape(-1, parts - 1)
    edges = np.hstack([np.full((len(bars), 1), -1), bars,
                       np.full((len(bars), 1), total + parts - 1)])
    return np.diff(edges, axis=1) - 1


def random_amounts(rng: np.random.Generator, plans: int, parts: int, budget: int,
                   min_part: int) -> np.ndarray:
    """Random whole-number amounts, each at least `min_part`, each row summing to `budget`."""
    spare = budget - parts * min_part
    if spare < 0:
        raise ValueError(f"{parts} parts of at least {min_part} exceed the budget of {budget}")
    cuts = np.sort(rng.integers(0, spare + 1, size=(plans, parts - 1)), axis=1)
    edges = np.hstack([np.zeros((plans, 1), int), cuts, np.full((plans, 1), spare)])
    return np.diff(edges, axis=1) + min_part
