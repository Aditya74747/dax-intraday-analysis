"""Static PNG charts for the report."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FuncFormatter, MultipleLocator, PercentFormatter  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]  # categorical slots 1-3, in fixed order
NEGATIVE = "#e34948"  # diverging pair: blue for up, red for down

EUROS = FuncFormatter(lambda x, _: f"€{x:,.0f}")

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"],
    "font.size": 10,
    "text.color": INK,
    "axes.labelcolor": INK_SECONDARY,
    "axes.edgecolor": AXIS,
    "axes.titlesize": 13,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "axes.titlepad": 14,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.axisbelow": True,
    "axes.grid.axis": "y",
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelcolor": INK_SECONDARY,
    "ytick.labelcolor": INK_SECONDARY,
    "legend.frameon": False,
    "lines.linewidth": 2,
})


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def _subtitle(ax: plt.Axes, text: str) -> None:
    ax.text(0, 1.01, text, transform=ax.transAxes, color=INK_SECONDARY, fontsize=9.5, va="bottom")


def price_history(daily: pd.DataFrame, events: dict[str, tuple[str, str]], path: Path) -> Path:
    """DAX close with the lowest point of each named sell-off marked."""
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.plot(daily.index, daily["Close"], color=SERIES[0], linewidth=1.6)
    for label, (start, end) in events.items():
        window = daily.loc[start:end, "Close"]
        if window.empty:
            continue
        day, low = window.idxmin(), window.min()
        ax.plot(day, low, "o", markersize=7, color=SERIES[0],
                markeredgecolor=SURFACE, markeredgewidth=2)
        ax.annotate(f"{label}\n{low:,.0f}", (day, low), xytext=(0, -10),
                    textcoords="offset points", ha="center", va="top",
                    fontsize=8.5, color=INK_SECONDARY)
    ax.set_ylim(0, daily["Close"].max() * 1.08)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.set_title("DAX index, daily close")
    _subtitle(ax, f"{daily.index[0]:%b %Y} to {daily.index[-1]:%b %Y}; dots mark the low of each sell-off")
    return _save(fig, path)


def plan_paths(paths: dict[str, pd.Series], path: Path) -> Path:
    """Value of the budget over time for up to three plans, labelled at the line ends."""
    fig, ax = plt.subplots(figsize=(10, 4.8))
    for color, (label, series) in zip(SERIES, paths.items()):
        ax.plot(series.index, series, color=color, label=label)
        ax.annotate(f"€{series.iloc[-1]:,.0f}", (series.index[-1], series.iloc[-1]),
                    xytext=(6, 0), textcoords="offset points", va="center",
                    fontsize=9, color=INK)
    ax.yaxis.set_major_formatter(EUROS)
    ax.set_ylim(bottom=0)
    ax.margins(x=0.06)
    ax.legend(loc="upper left")
    ax.set_title("Value of €10,000 under three buy-and-hold plans")
    _subtitle(ax, "Shares plus cash not yet invested; €1 fee per purchase")
    return _save(fig, path)


def fees_by_frequency(table: pd.DataFrame, budget: float, path: Path) -> Path:
    """Final value against the number of purchases, on a log scale."""
    data = table.sort_values("purchases")
    fig, ax = plt.subplots(figsize=(10, 4.4))
    ax.plot(data["purchases"], data["final_value"], color=SERIES[0],
            marker="o", markersize=8, markeredgecolor=SURFACE, markeredgewidth=2)
    ax.axhline(budget, color=AXIS, linewidth=1, linestyle="--")
    ax.text(data["purchases"].min(), budget, "money put in", color=MUTED,
            fontsize=8.5, ha="left", va="bottom")
    # First point labelled above, last point to its left, below the falling line.
    placements = [((0, 12), "left", "bottom"), ((-12, -4), "right", "center")]
    for (_, row), (offset, ha, va) in zip(data.iloc[[0, -1]].iterrows(), placements):
        count = int(row["purchases"])
        ax.annotate(f"€{row['final_value']:,.0f}\n{count:,} purchase{'s' if count > 1 else ''}",
                    (count, row["final_value"]), xytext=offset,
                    textcoords="offset points", ha=ha, va=va, fontsize=8.5)
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.yaxis.set_major_formatter(EUROS)
    ax.set_ylim(0, data["final_value"].max() * 1.2)
    ax.set_xlabel("Number of equal purchases (log scale)")
    ax.set_title("More purchases, more fees, less money")
    _subtitle(ax, "Final value of €10,000 split into equal purchases, €1 fee each")
    return _save(fig, path)


def random_plans(plans: pd.DataFrame, benchmark: float, path: Path, sample: int = 15_000,
                 seed: int = 0) -> Path:
    """Each random plan's final value against how long its money waited in cash."""
    shown = plans.sample(min(sample, len(plans)), random_state=seed)
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.scatter(shown["years_waited"], shown["final_value"], s=6, color=SERIES[0],
               alpha=0.25, linewidths=0)
    ax.axhline(benchmark, color=SERIES[1], linewidth=1.5)
    ax.text(shown["years_waited"].max(), benchmark, f"all at once on day 1: €{benchmark:,.0f}",
            color=INK, fontsize=9, ha="right", va="bottom")
    ax.yaxis.set_major_formatter(EUROS)
    ax.set_xlabel("Average years the money waited before being invested")
    ax.set_title("The longer money waits in cash, the less it grows")
    _subtitle(ax, f"{len(shown):,} of {len(plans):,} random plans; whole-euro splits, €1 fee per purchase")
    return _save(fig, path)


def hour_moves(stats: pd.DataFrame, path: Path) -> Path:
    """Average move inside each hourly bar, blue for up and red for down."""
    fig, ax = plt.subplots(figsize=(10, 4.2))
    colors = [SERIES[0] if v >= 0 else NEGATIVE for v in stats["average"]]
    ax.bar(stats.index, stats["average"], color=colors, width=0.6)
    ax.axhline(0, color=AXIS, linewidth=1)
    ax.yaxis.set_major_locator(MultipleLocator(0.00005))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:+.3%}" if x else "0%"))
    ax.set_title("Average DAX move within each trading hour")
    _subtitle(ax, "Frankfurt time, open to close of each hourly bar; blue = up, red = down")
    ax.tick_params(axis="x", labelsize=8.5)
    return _save(fig, path)


def hindsight_scatter(check: pd.DataFrame, path: Path) -> Path:
    """First-half against second-half return for every round-trip strategy."""
    fig, ax = plt.subplots(figsize=(7.5, 6))
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.axhline(0, color=AXIS, linewidth=1)
    ax.axvline(0, color=AXIS, linewidth=1)
    ax.scatter(check["first_half"], check["second_half"], s=40, color=SERIES[0],
               edgecolors=SURFACE, linewidths=1.5)
    # Label the first half's top three, nudged apart because #2 and #3 sit close together.
    offsets = [((8, 0), "left", "center"), ((8, -6), "left", "top"), ((8, 4), "left", "bottom")]
    for (name, row), (offset, ha, va) in zip(check.head(3).iterrows(), offsets):
        ax.annotate(f"{name}\n#{int(row['first_half_rank'])} → #{int(row['second_half_rank'])}",
                    (row["first_half"], row["second_half"]), xytext=offset,
                    textcoords="offset points", ha=ha, va=va, fontsize=8.5)
    for axis in (ax.xaxis, ax.yaxis):
        axis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_xlabel("Return in the first half (used to pick)")
    ax.set_ylabel("Return in the second half (unseen)")
    ax.set_title("Past winners did not keep winning")
    _subtitle(ax, "Each dot is one daily buy-at-hour / sell-at-hour strategy, before costs")
    return _save(fig, path)
