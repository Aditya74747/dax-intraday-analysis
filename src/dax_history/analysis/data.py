"""Load the price files written by the dax-history downloader."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..storage import load

DAILY_FILE = Path("data/dax_daily.csv")
HOURLY_FILE = Path("data/dax_hourly.csv")
DAILY_START = "2010-01-01"
# Xetra trades 09:00-17:30 Frankfurt time, so its hourly bars start at 09:00 to 17:00.
TRADING_HOURS = range(9, 18)


def load_daily(path: Path = DAILY_FILE) -> pd.DataFrame:
    data = load(path)
    if data.index.name != "Date":
        raise ValueError(f"{path} holds intraday data; expected daily prices.")
    # Drop the occasional broken row Yahoo serves with a zero price.
    return data[(data[["Open", "High", "Low", "Close"]] > 0).all(axis=1)]


def load_hourly(path: Path = HOURLY_FILE) -> pd.DataFrame:
    data = load(path)
    if data.index.name != "Datetime":
        raise ValueError(f"{path} holds daily data; expected hourly prices.")
    # Yahoo occasionally adds a stray bar outside trading hours.
    return data[data.index.hour.isin(TRADING_HOURS)]
