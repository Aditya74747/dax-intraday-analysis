import numpy as np
import pandas as pd
import pytest

from dax_history.analysis import intraday, metrics, plans, random_plans
from dax_history.analysis.report import markdown


def daily_prices(closes, start="2020-01-01") -> pd.DataFrame:
    """Daily OHLC where each day opens and closes at the same price."""
    index = pd.bdate_range(start, periods=len(closes), name="Date")
    closes = np.asarray(closes, float)
    return pd.DataFrame({"Open": closes, "High": closes * 1.01, "Low": closes * 0.99,
                         "Close": closes, "Volume": 0}, index=index)


def test_compositions_cover_every_split_once():
    rows = metrics.compositions(3, 3)
    assert len(rows) == 10  # (3 + 3 - 1) choose (3 - 1)
    assert (rows.sum(axis=1) == 3).all()
    assert len({tuple(r) for r in rows}) == 10


def test_random_amounts_are_whole_and_respect_budget_and_minimum():
    amounts = metrics.random_amounts(np.random.default_rng(0), 500, 7, 10_000, 50)
    assert amounts.dtype.kind == "i"
    assert (amounts.sum(axis=1) == 10_000).all()
    assert amounts.min() >= 50


def test_random_amounts_rejects_impossible_minimum():
    with pytest.raises(ValueError):
        metrics.random_amounts(np.random.default_rng(0), 1, 3, 100, 50)


def test_xirr_matches_cagr_for_a_single_payment():
    assert metrics.xirr([2.0], [100.0], 121.0) == pytest.approx(0.10, abs=1e-9)


def test_max_drawdown():
    assert metrics.max_drawdown([100, 120, 60, 130]) == pytest.approx(-0.5)


def test_lump_sum_pays_one_fee_and_grows_with_the_price():
    bt = plans.BuyOnly(daily_prices([100, 150, 200]), budget=1000, fee=1)
    result = bt.run("lump", bt.days[:1])
    assert result.final_value == pytest.approx(999 / 100 * 200)
    assert result.fees == 1
    assert result.path.iloc[0] == pytest.approx(999)


def test_uninvested_money_counts_as_cash():
    bt = plans.BuyOnly(daily_prices([100, 100, 200]), budget=1000, fee=0)
    result = bt.run("half", bt.days[:1], amounts=np.array([500.0]))
    assert result.final_value == pytest.approx(500 / 100 * 200 + 500)


def test_more_purchases_cost_more_fees_in_a_flat_market():
    bt = plans.BuyOnly(daily_prices([100] * 10), budget=1000, fee=1)
    assert bt.run("one", bt.days[:1]).final_value == pytest.approx(999)
    assert bt.run("ten", bt.days).final_value == pytest.approx(990)


def test_dip_dates_buy_the_day_after_a_fall_from_the_peak():
    prices = daily_prices([100, 95, 89, 90, 120, 100])
    dates = plans.dip_dates(prices, 0.10)
    # Day 2 closes 11% below the peak of 100, so the buy is at day 3's open.
    assert list(dates) == [prices.index[3]]


def test_exhaustive_best_split_buys_everything_at_the_cheapest_anchor():
    prices = daily_prices(np.r_[np.full(600, 100.0), np.full(600, 50.0), [200.0]])
    bt = plans.BuyOnly(prices, budget=3000, fee=0)
    entries, splits = plans.exhaustive_splits(bt, chunk=1000, step_years=2)
    assert len(entries) == 3
    assert splits.loc[0, "split"].startswith("€3,000 on")
    assert splits.loc[0, "final_value"] == pytest.approx(3000 / 50 * 200)


def test_monte_carlo_plans_spend_the_whole_budget():
    bt = plans.BuyOnly(daily_prices(np.linspace(100, 200, 300)), budget=1000, fee=1)
    result = random_plans.simulate(bt, plans=200, max_parts=10, min_part=50, seed=0)
    assert len(result.plans) == 200
    assert all(a.sum() == 1000 for a in result.amounts)
    assert result.plans["parts"].between(1, 10).all()


def hourly_prices() -> pd.DataFrame:
    """Two days of hourly bars; each bar rises 1 point and day two gaps up 10."""
    rows = []
    for day, base in [("2026-01-05", 100.0), ("2026-01-06", 120.0)]:
        for i, hour in enumerate(range(9, 18)):
            open_ = base + i
            rows.append((pd.Timestamp(f"{day} {hour:02d}:00"), open_, open_ + 1))
    index = pd.DatetimeIndex([r[0] for r in rows], name="Datetime")
    opens = [r[1] for r in rows]
    closes = [r[2] for r in rows]
    return pd.DataFrame({"Open": opens, "High": closes, "Low": opens, "Close": closes,
                         "Volume": 0}, index=index)


def test_round_trip_and_overnight_returns():
    returns = intraday.round_trip_returns(hourly_prices())
    assert len(returns.columns) == 46  # 45 intraday pairs + overnight
    assert returns["09:00→10:00"].iloc[0] == pytest.approx(1 / 100)
    assert returns["09:00→17:30"].iloc[0] == pytest.approx(9 / 100)
    # 17:30 close of day one is 109; 09:00 open of day two is 120.
    assert returns["overnight 17:30→09:00"].iloc[1] == pytest.approx(120 / 109 - 1)


def test_markdown_table():
    table = pd.DataFrame({"value": [1.5]}, index=pd.Index(["a"], name="name"))
    assert markdown(table, {"value": lambda v: f"{v:.1f}"}) == (
        "| name | value |\n| --- | ---: |\n| a | 1.5 |")
