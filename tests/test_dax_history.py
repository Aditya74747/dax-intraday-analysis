from datetime import date, timedelta

import openpyxl
import pandas as pd
import pytest

import dax_history
from dax_history import fetch


def yahoo_frame(timestamps=("2026-01-05", "2026-01-02")) -> pd.DataFrame:
    """Mimic yfinance output: (field, ticker) columns and a UTC time index."""
    fields = ["Adj Close", "Close", "High", "Low", "Open", "Volume"]
    columns = pd.MultiIndex.from_product(
        [fields, ["^GDAXI"]], names=["Price", "Ticker"]
    )
    index = pd.to_datetime(list(timestamps), utc=True)
    index.name = "Date"
    rows = [[n, n, n + 0.5, n - 0.5, n - 0.2, n * 100] for n in range(len(index), 0, -1)]
    return pd.DataFrame(rows, index=index, columns=columns, dtype=float)


# 08:00 and 08:30 UTC are 09:00 and 09:30 in Frankfurt during winter time.
INTRADAY = ("2026-01-05 08:30", "2026-01-05 08:00")


class Downloads(list):
    """Records yf.download calls; `frame` is what each call returns."""

    frame = yahoo_frame()

    def set_frame(self, timestamps):
        self.frame = yahoo_frame(timestamps)


@pytest.fixture
def download(monkeypatch):
    calls = Downloads()

    def fake_download(ticker, **kwargs):
        calls.append((ticker, kwargs))
        return calls.frame

    monkeypatch.setattr(fetch.yf, "download", fake_download)
    return calls


@pytest.fixture
def intraday(download):
    download.set_frame(INTRADAY)
    return download


def test_fetch_flattens_sorts_and_includes_end_date(download):
    data = dax_history.fetch_history("^GDAXI", date(2026, 1, 1), date(2026, 1, 5))

    assert list(data.columns) == dax_history.COLUMNS
    assert data.index.name == "Date"
    assert data.index.tz is None
    assert data.index.is_monotonic_increasing
    assert data.loc["2026-01-05", "Close"] == 2.0
    assert download[0][1]["end"] == "2026-01-06"
    assert download[0][1]["interval"] == "1d"


def test_fetch_raises_when_no_data(monkeypatch):
    monkeypatch.setattr(fetch.yf, "download", lambda *a, **k: pd.DataFrame())
    with pytest.raises(RuntimeError, match="no 1h data"):
        dax_history.fetch_history("^GDAXI", date(2026, 1, 1), date(2026, 1, 5), "1h")


def test_fetch_intraday_uses_frankfurt_time(intraday):
    data = dax_history.fetch_history("^GDAXI", date(2026, 1, 5), date(2026, 1, 5), "30m")

    assert data.index.name == "Datetime"
    assert data.index.tz is None
    assert list(data.index) == list(pd.to_datetime(["2026-01-05 09:00", "2026-01-05 09:30"]))


def test_fetch_splits_one_minute_requests_into_weeks(intraday):
    dax_history.fetch_history("^GDAXI", date(2026, 1, 1), date(2026, 1, 20), "1m")

    ranges = [(kwargs["start"], kwargs["end"]) for _, kwargs in intraday]
    assert ranges == [
        ("2026-01-01", "2026-01-08"),
        ("2026-01-08", "2026-01-15"),
        ("2026-01-15", "2026-01-21"),
    ]


def test_date_chunks_cover_range_without_overlap():
    chunks = list(fetch.date_chunks(date(2026, 1, 1), date(2026, 1, 15), 7))
    assert chunks == [
        (date(2026, 1, 1), date(2026, 1, 7)),
        (date(2026, 1, 8), date(2026, 1, 14)),
        (date(2026, 1, 15), date(2026, 1, 15)),
    ]


@pytest.mark.parametrize("name", ["out.csv", "nested/out.xlsx"])
def test_main_round_trips_file(download, tmp_path, name):
    output = tmp_path / name
    assert dax_history.main(["--output", str(output), "--years", "1"]) == 0

    saved = dax_history.load(output)
    assert list(saved.columns) == dax_history.COLUMNS
    assert list(saved.index) == list(pd.to_datetime(["2026-01-02", "2026-01-05"]))
    assert saved["Close"].tolist() == [1.0, 2.0]


@pytest.mark.parametrize("name", ["out.csv", "out.xlsx"])
def test_main_round_trips_intraday_file(intraday, tmp_path, name):
    output = tmp_path / name
    assert dax_history.main(["--output", str(output), "--interval", "30m"]) == 0

    saved = dax_history.load(output)
    assert saved.index.name == "Datetime"
    assert list(saved.index) == list(pd.to_datetime(["2026-01-05 09:00", "2026-01-05 09:30"]))


def test_excel_date_formats(download, tmp_path):
    daily, hourly = tmp_path / "daily.xlsx", tmp_path / "hourly.xlsx"
    assert dax_history.main(["--output", str(daily), "--years", "1"]) == 0
    download.set_frame(INTRADAY)
    assert dax_history.main(["--output", str(hourly), "--interval", "1h"]) == 0

    assert openpyxl.load_workbook(daily).active["A2"].number_format == "YYYY-MM-DD"
    assert openpyxl.load_workbook(hourly).active["A2"].number_format == "YYYY-MM-DD HH:MM"


def test_intraday_start_is_clamped_to_yahoo_window(intraday, tmp_path, capsys):
    assert dax_history.main(["--output", str(tmp_path / "out.csv"), "--interval", "1h"]) == 0

    earliest = date.today() - timedelta(days=dax_history.INTERVALS["1h"].max_age_days)
    assert intraday[0][1]["start"] == earliest.isoformat()
    assert "only keeps 1h data" in capsys.readouterr().err


def test_intraday_range_entirely_too_old_is_rejected(capsys):
    with pytest.raises(SystemExit):
        dax_history.main(["--interval", "30m", "--start", "2010-01-01", "--end", "2010-02-01"])
    assert "only keeps 30m data" in capsys.readouterr().err


def test_append_keeps_old_rows_and_prefers_new_ones(intraday, tmp_path):
    output = tmp_path / "out.csv"
    old = pd.DataFrame(
        [[1, 1, 1, 1, 0], [9, 9, 9, 9, 0]],
        index=pd.to_datetime(["2025-12-30 17:00", "2026-01-05 09:00"]).rename("Datetime"),
        columns=dax_history.COLUMNS,
        dtype=float,
    )
    dax_history.save(old, output)

    assert dax_history.main(["--output", str(output), "--interval", "30m", "--append"]) == 0

    saved = dax_history.load(output)
    assert len(saved) == 3
    assert saved.loc["2025-12-30 17:00", "Close"] == 1
    assert saved.loc["2026-01-05 09:00", "Close"] == 1  # replaced by the new download


def test_append_rejects_mixing_daily_and_intraday(intraday, tmp_path, capsys):
    output = tmp_path / "out.csv"
    daily = pd.DataFrame(
        [[1, 1, 1, 1, 0]],
        index=pd.to_datetime(["2026-01-02"]).rename("Date"),
        columns=dax_history.COLUMNS,
        dtype=float,
    )
    dax_history.save(daily, output)

    assert dax_history.main(["--output", str(output), "--interval", "1h", "--append"]) == 1
    assert "Can't append intraday data" in capsys.readouterr().err


def test_rejects_unknown_output_type(capsys):
    with pytest.raises(SystemExit):
        dax_history.main(["--output", "dax.json"])
    assert ".csv or .xlsx" in capsys.readouterr().err


def test_rejects_start_after_end():
    with pytest.raises(SystemExit):
        dax_history.main(["--start", "2026-02-01", "--end", "2026-01-01"])


def test_subtract_years_handles_leap_day():
    assert dax_history.subtract_years(date(2024, 2, 29), 10) == date(2014, 2, 28)
