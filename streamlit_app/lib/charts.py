# =============================================================================
# lib/charts.py -- forecast chart for the web and PDF
# =============================================================================
# Revenue and EBIT across the full timeline (actuals + forecast), with the
# actuals-to-forecast boundary marked. Dual y-axes keep both readable despite
# the ~9x scale difference.
# =============================================================================

import matplotlib
matplotlib.use("Agg")

from matplotlib import pyplot as plt
import matplotlib.ticker as mticker
from io import BytesIO

from config import CURRENCY_SYMBOL, REVENUE_ITEMS, COGS_ITEMS, OPEX_ITEMS

DARK_BLUE  = "#1A3A5C"
MID_BLUE   = "#2D6A9F"
MUTED      = "#898781"
GREEN      = "#1D6B0F"
LIGHT_BLUE = "#EAF2FB"
RULE       = "#D3D1C7"

_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _thousands(x, _pos):
    return "{:,.0f}".format(x)


def build_forecast_chart(full_df, last_actual, forecast_periods):
    """Revenue and EBIT across all periods, actuals/forecast boundary marked.

    Returns a matplotlib Figure (caller must close it after display).
    """
    all_periods = sorted(full_df["period"].unique())

    revenue = []
    ebit = []
    for p in all_periods:
        pdf = full_df[full_df["period"] == p]
        rev = float(pdf[pdf["line_item"].isin(REVENUE_ITEMS)]["value"].sum())
        cogs = float(pdf[pdf["line_item"].isin(COGS_ITEMS)]["value"].sum())
        opex = float(pdf[pdf["line_item"].isin(OPEX_ITEMS)]["value"].sum())
        revenue.append(rev)
        ebit.append(rev - cogs - opex)

    labels = []
    for p in all_periods:
        m = _MONTH_ABBR[int(p[5:7]) - 1]
        if p.endswith("-01") or p == all_periods[0]:
            labels.append(m + "\n" + p[:4])
        else:
            labels.append(m)

    fig, ax1 = plt.subplots(figsize=(6.5, 3.0), dpi=150)
    xs = list(range(len(all_periods)))

    ax1.plot(xs, revenue, color=MID_BLUE, linewidth=1.8,
             marker="o", markersize=3, label="Revenue", zorder=3)
    ax1.set_ylabel("Revenue ({})".format(CURRENCY_SYMBOL),
                    fontsize=9, color=MID_BLUE)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(_thousands))
    ax1.tick_params(axis="y", labelsize=8, colors=MID_BLUE)

    ax2 = ax1.twinx()
    ax2.plot(xs, ebit, color=GREEN, linewidth=1.8,
             marker="o", markersize=3, label="EBIT", zorder=3)
    ax2.set_ylabel("EBIT ({})".format(CURRENCY_SYMBOL),
                    fontsize=9, color=GREEN)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(_thousands))
    ax2.tick_params(axis="y", labelsize=8, colors=GREEN)

    boundary_idx = all_periods.index(last_actual) + 0.5
    ax1.axvspan(-0.5, boundary_idx, color=LIGHT_BLUE, alpha=0.35, zorder=0)
    ax1.axvline(boundary_idx, color=RULE, linestyle="--", linewidth=1, zorder=1)
    mid_a = boundary_idx / 2
    mid_f = (boundary_idx + len(all_periods) - 0.5) / 2
    ax1.text(mid_a, 0.97, "Actuals", transform=ax1.get_xaxis_transform(),
             ha="center", va="top", fontsize=7.5, color=MUTED)
    ax1.text(mid_f, 0.97, "Forecast", transform=ax1.get_xaxis_transform(),
             ha="center", va="top", fontsize=7.5, color=MUTED)

    ax1.set_xticks(xs)
    ax1.set_xticklabels(labels, fontsize=7)
    ax1.spines["top"].set_visible(False)
    ax2.spines["top"].set_visible(False)
    ax1.grid(axis="y", color=RULE, linewidth=0.5, alpha=0.5)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2,
               fontsize=8, loc="upper left", framealpha=0.9)

    fig.tight_layout()
    return fig


def chart_png_bytes(fig):
    """Render a figure to PNG bytes for embedding in a PDF."""
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf
