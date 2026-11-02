"""Read, merge and write price files as CSV or Excel."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .fetch import COLUMNS

SUPPORTED_SUFFIXES = {".csv", ".xlsx"}
# One row is taken by the header.
EXCEL_MAX_ROWS = 1_048_575


def check_suffix(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type {suffix!r}: use .csv or .xlsx.")
    return suffix


def save(data: pd.DataFrame, output: Path) -> None:
    """Write the data to `output`, choosing the format from the file extension."""
    suffix = check_suffix(output)
    intraday = data.index.name == "Datetime"

    output.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".csv":
        data.to_csv(output, date_format="%Y-%m-%d %H:%M" if intraday else "%Y-%m-%d")
        return

    if len(data) > EXCEL_MAX_ROWS:
        raise ValueError(
            f"{len(data)} rows don't fit in an Excel sheet; save to .csv instead."
        )
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        data.to_excel(writer, sheet_name="DAX")
        sheet = writer.sheets["DAX"]
        sheet.freeze_panes = "B2"
        number_format = "YYYY-MM-DD HH:MM" if intraday else "YYYY-MM-DD"
        for (cell,) in sheet.iter_rows(min_row=2, max_col=1):
            cell.number_format = number_format
        sheet.column_dimensions["A"].width = 17 if intraday else 12
        for column in "BCDEF":
            sheet.column_dimensions[column].width = 14


def load(path: Path) -> pd.DataFrame:
    """Read a file previously written by `save`."""
    if check_suffix(path) == ".csv":
        data = pd.read_csv(path, index_col=0, parse_dates=[0])
    else:
        data = pd.read_excel(path, index_col=0)
        data.index = pd.to_datetime(data.index)

    if list(data.columns) != COLUMNS or data.index.name not in {"Date", "Datetime"}:
        raise ValueError(f"{path} was not written by dax-history, so it can't be appended to.")
    return data


def merge(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Combine two price tables; where both have a row, the new one wins."""
    if existing.index.name != new.index.name:
        kinds = {"Date": "daily", "Datetime": "intraday"}
        raise ValueError(
            f"Can't append {kinds[new.index.name]} data to a file holding "
            f"{kinds[existing.index.name]} data; choose another --output."
        )
    combined = pd.concat([existing, new])
    return combined[~combined.index.duplicated(keep="last")].sort_index()
