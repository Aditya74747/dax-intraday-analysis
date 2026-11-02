"""Download DAX prices from Yahoo Finance at daily or intraday intervals."""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

# yfinance 1.7 triggers this pandas 3.1 deprecation warning on every download.
warnings.filterwarnings("ignore", message="The inplace keyword", module="yfinance")

DAX_TICKER = "^GDAXI"
COLUMNS = ["Open", "High", "Low", "Close", "Volume"]
EXCHANGE_TZ = "Europe/Berlin"


@dataclass(frozen=True)
class IntervalLimits:
    # How many days back Yahoo keeps this interval (None: no limit).
    max_age_days: int | None
    # Longest range Yahoo serves in one request (None: no limit).
    max_request_days: int | None


# Yahoo's limits, each kept one day inside the documented value so a request
# made late in the day still fits.
INTERVALS = {
    "1d": IntervalLimits(None, None),
    "1h": IntervalLimits(729, None),
    "30m": IntervalLimits(59, None),
    "15m": IntervalLimits(59, None),
    "5m": IntervalLimits(59, None),
    "1m": IntervalLimits(29, 7),
}


def is_intraday(interval: str) -> bool:
    return interval != "1d"


def earliest_start(interval: str, today: date) -> date | None:
    """Return the first date Yahoo still has data for, or None if unlimited."""
    days = INTERVALS[interval].max_age_days
    return None if days is None else today - timedelta(days=days)


def date_chunks(
    start: date, end: date, max_days: int | None
) -> Iterator[tuple[date, date]]:
    """Split start to end (both inclusive) into ranges of at most `max_days`."""
    if max_days is None:
        yield start, end
        return
    while start <= end:
        chunk_end = min(start + timedelta(days=max_days - 1), end)
        yield start, chunk_end
        start = chunk_end + timedelta(days=1)


def fetch_history(
    ticker: str, start: date, end: date, interval: str = "1d"
) -> pd.DataFrame:
    """Fetch prices from Yahoo Finance for start to end, both inclusive.

    Daily data is indexed by "Date". Intraday data is indexed by "Datetime"
    in Frankfurt local time, each row being the bar that starts at that time.
    """
    limits = INTERVALS[interval]
    frames = [
        download(ticker, chunk_start, chunk_end, interval)
        for chunk_start, chunk_end in date_chunks(start, end, limits.max_request_days)
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        raise RuntimeError(
            f"Yahoo Finance returned no {interval} data for {ticker} "
            f"between {start} and {end}. Check your internet connection and the "
            "ticker, or try again later in case Yahoo is rate-limiting you."
        )

    data = pd.concat(frames)
    return data[~data.index.duplicated(keep="last")].sort_index()


def download(ticker: str, start: date, end: date, interval: str) -> pd.DataFrame:
    """Make one Yahoo request and return it cleaned, or an empty frame."""
    raw = yf.download(
        ticker,
        start=start.isoformat(),
        # yfinance treats `end` as exclusive.
        end=(end + timedelta(days=1)).isoformat(),
        interval=interval,
        auto_adjust=False,
        progress=False,
    )
    if raw is None or raw.empty:
        return pd.DataFrame(columns=COLUMNS)

    # yfinance returns (field, ticker) column pairs, even for a single ticker.
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.droplevel("Ticker", axis=1)

    data = raw[COLUMNS].dropna(subset=["Close"]).copy()
    index = pd.to_datetime(data.index)
    if is_intraday(interval):
        # Excel can't store time zones, so keep Frankfurt wall-clock time.
        if index.tz is not None:
            index = index.tz_convert(EXCHANGE_TZ).tz_localize(None)
        index.name = "Datetime"
    else:
        index = index.tz_localize(None).normalize()
        index.name = "Date"
    data.index = index
    data.columns.name = None
    return data
