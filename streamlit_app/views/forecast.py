# =============================================================================
# views/forecast.py: base and adjusted forecast display (Phases 3+4+5+6)
# =============================================================================
# Two tabs under the banner, as on Project 6. "View a worked example", open
# on arrival, shows the base forecast with the commentary saved from a real
# run. "Run it yourself" holds the live run: the driver panel lets the user
# change any of the six line drivers, then click "Re-forecast" to recompute;
# "Reset defaults" returns to the base forecast.
#
# Widget-state design (the known-hard part):
#   Every control has a stable key; its value lives in st.session_state.
#   The "Re-forecast" button reads the current state, builds overrides, and
#   runs the engine. No widget relies on value= to carry state across reruns;
#   method-selector changes trigger a rerun for relabelling, and the value
#   inputs survive that rerun via their keys.
#
# Sign-off (after Project 6; the rule and its messages live in
# src/signoff.py): once the forecast on screen has commentary, the live run
# ends with a Sign-off section. A named reviewer types SIGN and the result is
# FINAL, in the PDF and in that run's session audit row. The sign-off holds
# only for the result it was made for: a Re-forecast that changes the
# figures, or a new Write commentary, is a new DRAFT. While the drivers in
# the panel differ from the forecast on screen, Sign off waits for a
# Re-forecast. The PDF button sits inside the Sign-off section, in Project
# 4's order; before there is commentary to sign there is no section, and the
# DRAFT PDF sits in the downloads row beside the CSV.
# =============================================================================

import hashlib
import html
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit_app.lib.theme import inject_css, header_html, status_chip_html
from streamlit_app.lib.driver_menu import (
    LINE_DEFAULTS, ALLOWED_METHODS, METHOD_LABEL, METHOD_VALUE_SHAPE,
)
from streamlit_app.lib.driver_controls import (
    to_display, build_overrides, override_note,
)
from streamlit_app.lib.charts import build_forecast_chart
from streamlit_app.lib.commentary import (
    forecast_fingerprint, parse_sections, section_to_html,
)
from streamlit_app.lib.cost import format_cost
from streamlit_app.lib.errors import friendly_message, model_failure_message
from streamlit_app.lib.audit import record_run, get_runs, add_signoff
from streamlit_app.lib.example_run import EXAMPLE
from src.step3_ai_engine import build_prompt
from src.step4_output_writer import (
    build_pdf_bytes, build_csv_bytes, compute_data_hashes, check_requires_review,
)
from src.signoff import (
    FINAL, SCOPE_NOTE, STALE_CAPTION, WORD_HELP, WORD_LABEL, SignOff,
    pdf_status_line, sign_off,
)

from src.step1_data_loader import (
    load_actuals, load_drivers, detect_boundary,
    load_operational_actuals, load_headcount_schedule, load_customer_targets,
)
from src.step2_forecast_engine import calculate_forecast, build_pnl
from config import (
    ACTUALS_FILE, DRIVER_FILE, OPERATIONAL_FILE, HEADCOUNT_FILE,
    CUSTOMER_FILE, CURRENCY_SYMBOL, REVENUE_ITEMS, COGS_ITEMS, OPEX_ITEMS,
    MODEL, MAX_TOKENS,
)


# ---------------------------------------------------------------------------
# Data loading (cached) and forecast computation
# ---------------------------------------------------------------------------

@st.cache_data
def _load_data():
    """Cache-once data loading from the five CSV files."""
    actuals_df  = load_actuals(ACTUALS_FILE)
    drivers_df  = load_drivers(DRIVER_FILE)
    operational = load_operational_actuals(OPERATIONAL_FILE)
    headcount   = load_headcount_schedule(HEADCOUNT_FILE)
    customers   = load_customer_targets(CUSTOMER_FILE)
    last_actual, forecast_periods = detect_boundary(actuals_df)
    seasonal_year = int(last_actual.split("-")[0]) - 1
    return (actuals_df, drivers_df, operational, headcount, customers,
            last_actual, forecast_periods, seasonal_year)


@st.cache_data
def _base_forecast():
    """Cache-once base forecast (no overrides)."""
    (actuals_df, drivers_df, operational, headcount, customers,
     last_actual, forecast_periods, seasonal_year) = _load_data()
    full_df, driver_detail, flags = calculate_forecast(
        actuals_df, drivers_df, operational, headcount, customers,
        last_actual, forecast_periods, seasonal_year,
    )
    pnl_df = build_pnl(full_df, forecast_periods)
    return full_df, pnl_df, driver_detail, flags, last_actual, forecast_periods


def _adjusted_forecast(overrides):
    """Recompute the forecast with driver overrides (uses cached data)."""
    (actuals_df, drivers_df, operational, headcount, customers,
     last_actual, forecast_periods, seasonal_year) = _load_data()
    full_df, driver_detail, flags = calculate_forecast(
        actuals_df, drivers_df, operational, headcount, customers,
        last_actual, forecast_periods, seasonal_year,
        driver_overrides=overrides,
    )
    pnl_df = build_pnl(full_df, forecast_periods)
    return full_df, pnl_df, driver_detail, flags, last_actual, forecast_periods


def _panel_method(driver_type):
    """The driver panel's method for a driver file's driver type:
    fixed_growth, the older name of growth_pct, is month-on-month growth."""
    return "growth_pct" if driver_type == "fixed_growth" else driver_type


def _effective_drivers(base_drivers_df, overrides):
    """Return a drivers_df reflecting any user overrides, so build_prompt
    and the PDF driver table show the adjusted assumptions rather than the
    CSV defaults. A line whose method or value changed gets a note stating
    the new value (its CSV note states the old one); a line left at its CSV
    driver keeps its row as the CSV has it (fixed_growth and growth_pct are
    the same method)."""
    if not overrides:
        return base_drivers_df
    df = base_drivers_df.copy()
    if "note" not in df.columns:
        df["note"] = ""
    for line, ov in overrides.items():
        mask = df["line_item"] == line
        if mask.any():
            base = df.loc[mask].iloc[0]
            changed = (ov["method"] != _panel_method(base["driver_type"])
                       or not math.isclose(
                           float(ov["value"]), float(base["driver_value"]),
                           rel_tol=1e-9, abs_tol=1e-12))
            if changed:
                df.loc[mask, "driver_type"] = ov["method"]
                df.loc[mask, "driver_value"] = ov["value"]
                df.loc[mask, "note"] = override_note(ov["method"], ov["value"])
    return df


def _file_values(overrides):
    """The panel's overrides, with each line left at the driver file's
    driver sending the file's own value. A value box holds the display form
    (a percentage times 100), which does not always turn back into the same
    float, so this keeps an untouched Re-forecast exactly the base forecast."""
    rows = {row["line_item"]: row for _, row in _load_data()[1].iterrows()}
    for line, ov in (overrides or {}).items():
        row = rows.get(line)
        if (row is not None
                and ov["method"] == _panel_method(row["driver_type"])
                and math.isclose(float(ov["value"]), float(row["driver_value"]),
                                 rel_tol=1e-9, abs_tol=1e-12)):
            ov["value"] = row["driver_value"]
    return overrides


# ---------------------------------------------------------------------------
# P&L table builder (monthly + YTD/YTG/FY, EUR '000)
# ---------------------------------------------------------------------------

_MONTH_LABELS = {
    "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
    "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
    "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
}


_EXPENSE_LINES = {"COGS"} | set(OPEX_ITEMS) | {"Total OpEx"}
_SUMMARY_LINES = {"Gross Profit", "Total OpEx", "Operating Profit (EBIT)"}
_TOPLINE_LINES = {"Gross Profit", "Total OpEx"}
_BOTTOMLINE_LINES = {"Operating Profit (EBIT)"}


def _fmt_pnl_cell(val, is_expense):
    """Format a P&L cell in EUR '000 with accounting parentheses."""
    v = val / 1000.0
    if is_expense:
        return "({:,.0f})".format(abs(v))
    return "{:,.0f}".format(v)


_SUMMARY_COLS = {"YTD", "YTG", "FY"}
_ANALYSIS_COLS = {"% Rev"}


def _kpi_row_html(title, cards_data):
    """Render a titled row of KPI cards. cards_data: [(label, value, sub)...]"""
    from streamlit_app.lib.theme import DARK_BLUE, LIGHT_BLUE, MUTED, SANS
    cards = []
    for label, value, sub in cards_data:
        sub_html = ""
        if sub:
            sub_html = ('<div class="sc-kpi-figure" '
                        'style="font-size:0.78rem;margin-top:2px">'
                        '{}</div>').format(sub)
        # Tiles share a row on wide screens and stack on a phone
        cards.append(
            '<div style="flex:1 1 180px;min-width:0;background:{};'
            'border-left:4px solid {};border-radius:8px;padding:14px 18px">'
            '<div style="font-size:0.72rem;color:{};font-weight:600;'
            'letter-spacing:0.05em;text-transform:uppercase">{}</div>'
            '<div class="sc-kpi-figure" style="font-size:1.4rem;'
            'font-weight:700;color:{};margin-top:4px">{}</div>'
            '{}</div>'.format(LIGHT_BLUE, DARK_BLUE, MUTED, label,
                              DARK_BLUE, value, sub_html)
        )
    return (
        '<div style="margin-bottom:10px">'
        '<div style="font-size:0.82rem;font-weight:600;color:{};'
        'margin-bottom:8px">{}</div>'
        '<div style="display:flex;flex-wrap:wrap;gap:12px">{}</div>'
        '</div>'.format(DARK_BLUE, title, "".join(cards))
    )


def _hoh_badge(h2, h1):
    """Half-on-half change badge for KPI cards."""
    from streamlit_app.lib.theme import GREEN, FLAG_RED
    if h1 == 0:
        return ""
    pct = (h2 - h1) / abs(h1) * 100
    sign = "+" if pct >= 0 else ""
    color = GREEN if pct >= 0 else FLAG_RED
    return ('<span style="font-size:0.78rem;font-weight:600;color:{}">'
            '{}{:.1f}% vs H1</span>').format(color, sign, pct)


def _build_pnl_html(pnl_df, full_df, forecast_periods):
    """Build an HTML table with proper P&L formatting."""
    from streamlit_app.lib.theme import (
        DARK_BLUE, MUTED, RULE, NEAR_WHITE, LIGHT_BLUE, SANS,
    )

    fcst_year = forecast_periods[0][:4]
    ytd_periods = sorted(
        full_df[
            (full_df["type"] == "actual")
            & (full_df["period"].str.startswith(fcst_year))
        ]["period"].unique()
    )

    def _actual_sum(items, periods):
        return float(full_df[
            (full_df["type"] == "actual")
            & (full_df["line_item"].isin(items))
            & (full_df["period"].isin(periods))
        ]["value"].sum())

    month_cols = [_MONTH_LABELS[p[5:7]] for p in forecast_periods]
    all_cols = month_cols + ["YTD", "YTG", "FY", "% Rev"]

    _rev_row = pnl_df[pnl_df["line"] == "Revenue"]
    _rev_ytg = float(_rev_row["total"].iloc[0])
    _rev_ytd = _actual_sum(REVENUE_ITEMS, ytd_periods)
    _fy_rev = _rev_ytd + _rev_ytg

    th_base = ("text-align:right;padding:7px 10px;font-weight:600;"
               "font-size:0.8rem;letter-spacing:0.03em")
    hdr = ("<tr><th style='text-align:left;padding:7px 12px;"
            "min-width:180px;font-weight:600;font-size:0.8rem;"
            "letter-spacing:0.03em'></th>")
    for c in all_cols:
        extra = ""
        if c == "YTD":
            extra = "border-left:2px solid {};".format(DARK_BLUE)
        if c in _SUMMARY_COLS:
            extra += "background:{};font-weight:700;".format(LIGHT_BLUE)
        if c in _ANALYSIS_COLS:
            extra += ("border-left:2px solid {};background:{};"
                      "font-style:italic;").format(RULE, NEAR_WHITE)
        hdr += "<th style='{};{}'>{}</th>".format(th_base, extra, c)
    hdr += "</tr>"

    rows_html = []
    for _, row in pnl_df.iterrows():
        line = row["line"]
        is_expense = line in _EXPENSE_LINES
        is_summary = line in _SUMMARY_LINES

        if line == "Revenue":
            ytd = _actual_sum(REVENUE_ITEMS, ytd_periods)
        elif line == "COGS":
            ytd = _actual_sum(COGS_ITEMS, ytd_periods)
        elif line == "Gross Profit":
            ytd = (_actual_sum(REVENUE_ITEMS, ytd_periods)
                   - _actual_sum(COGS_ITEMS, ytd_periods))
        elif line in OPEX_ITEMS:
            ytd = _actual_sum([line], ytd_periods)
        elif line == "Total OpEx":
            ytd = _actual_sum(OPEX_ITEMS, ytd_periods)
        elif line == "Operating Profit (EBIT)":
            ytd = (_actual_sum(REVENUE_ITEMS, ytd_periods)
                   - _actual_sum(COGS_ITEMS, ytd_periods)
                   - _actual_sum(OPEX_ITEMS, ytd_periods))
        else:
            ytd = 0.0

        ytg = float(row["total"])
        fy = ytd + ytg

        vals = {}
        for p in forecast_periods:
            vals[_MONTH_LABELS[p[5:7]]] = float(row[p])
        vals["YTD"] = ytd
        vals["YTG"] = ytg
        vals["FY"] = fy
        vals["% Rev"] = (fy / _fy_rev * 100) if _fy_rev else 0.0

        tr_style = ""
        if line in _TOPLINE_LINES:
            tr_style = "border-top:1.5px solid {};".format(DARK_BLUE)
        elif line in _BOTTOMLINE_LINES:
            tr_style = ("border-top:2.5px double {};"
                        "border-bottom:2.5px double {};").format(
                            DARK_BLUE, DARK_BLUE)

        weight = "700" if is_summary else "400"
        indent = "" if is_summary or line == "Revenue" else "padding-left:24px;"

        td_line = ("<td style='text-align:left;padding:5px 12px;"
                    "white-space:nowrap;min-width:180px;"
                    "font-weight:{};{}'>{}</td>").format(weight, indent, line)

        cells = td_line
        for c in all_cols:
            col_extra = ""
            if c == "YTD":
                col_extra = "border-left:2px solid {};".format(DARK_BLUE)
            if c in _SUMMARY_COLS:
                col_extra += ("background:{};font-weight:700;"
                              "color:{};").format(LIGHT_BLUE, DARK_BLUE)
            if c in _ANALYSIS_COLS:
                col_extra += ("border-left:2px solid {};background:{};"
                              "font-style:italic;font-size:0.82rem;"
                              "color:{};").format(RULE, NEAR_WHITE, MUTED)
            if c in _ANALYSIS_COLS:
                cell_text = "{:.1f}%".format(vals[c])
            else:
                cell_text = _fmt_pnl_cell(vals[c], is_expense)
            cells += ("<td style='text-align:right;padding:5px 10px;"
                      "font-weight:{};{}'>{}</td>").format(
                          weight if c not in _SUMMARY_COLS else "700",
                          col_extra,
                          cell_text)

        rows_html.append(
            "<tr style='{}'>{}</tr>".format(tr_style, cells))

    return (
        "<div style='overflow-x:auto'>"
        "<table style='width:100%;border-collapse:collapse;"
        "font-family:{};font-size:0.88rem;"
        "font-feature-settings:\"tnum\" 1'>"
        "<thead style='border-bottom:2px solid {};color:{}'>"
        "{}</thead><tbody>{}</tbody></table></div>"
    ).format(SANS, DARK_BLUE, MUTED, hdr, "".join(rows_html))


# ---------------------------------------------------------------------------
# Widget-state helpers
# ---------------------------------------------------------------------------

_LINE_KEYS = {line: line.lower().replace(" ", "_") for line in LINE_DEFAULTS}

_VALUE_LABELS = {
    "seasonal_yoy": "Annual growth %",
    "growth_pct":    "Monthly growth %",
    "margin_pct":    "Margin %",
    "fixed":         "Monthly amount ({})".format(CURRENCY_SYMBOL),
}


# The live commentary: its text, token counts, the forecast it was written
# for, its stop reason, and its run (the run's audit row timestamp)
_COMMENTARY_KEYS = ("_commentary_text", "_commentary_cost", "_commentary_fp",
                    "_commentary_stop", "_commentary_run")


def _file_drivers():
    """Each line's driver in the loaded driver file, the one the base
    forecast uses, as the panel shows it: {line: {"method", "value"}}, in
    the shape of LINE_DEFAULTS. fixed_growth shows as growth_pct, and a
    schedule has no value. A line the file does not list falls back to
    LINE_DEFAULTS."""
    rows = {row["line_item"]: row for _, row in _load_data()[1].iterrows()}
    drivers = {}
    for line, dflt in LINE_DEFAULTS.items():
        if line not in rows:
            drivers[line] = dflt
            continue
        method = _panel_method(rows[line]["driver_type"])
        drivers[line] = {
            "method": method,
            "value": (None if METHOD_VALUE_SHAPE[method] == "schedule"
                      else float(rows[line]["driver_value"]))}
    return drivers


def _init_state():
    """Seed session state with the driver file's drivers on first load."""
    if "_drv_init" in st.session_state:
        return
    for line, dflt in _file_drivers().items():
        k = _LINE_KEYS[line]
        st.session_state["method_{}".format(k)] = dflt["method"]
        st.session_state["_prev_{}".format(k)]  = dflt["method"]
        if dflt["value"] is not None:
            st.session_state["value_{}".format(k)] = to_display(
                dflt["method"], dflt["value"])
    st.session_state["_drv_init"] = True
    st.session_state["_adjusted"] = False


def _detect_method_changes():
    """If a method selector changed since the last render, set a value for
    the new method before widgets render: the driver file's value when the
    line is back on the file's method, else a sensible default."""
    for line, dflt in _file_drivers().items():
        k = _LINE_KEYS[line]
        cur  = st.session_state.get("method_{}".format(k), dflt["method"])
        prev = st.session_state.get("_prev_{}".format(k), cur)
        if cur == prev:
            continue
        if cur == dflt["method"] and dflt["value"] is not None:
            st.session_state["value_{}".format(k)] = to_display(
                cur, dflt["value"])
        elif METHOD_VALUE_SHAPE[cur] == "pct":
            st.session_state["value_{}".format(k)] = 5.0
        elif METHOD_VALUE_SHAPE[cur] == "currency":
            st.session_state["value_{}".format(k)] = 0.0
        st.session_state["_prev_{}".format(k)] = cur


def _reset_to_defaults():
    """Reset all driver controls to their CSV defaults."""
    for line, dflt in _file_drivers().items():
        k = _LINE_KEYS[line]
        st.session_state["method_{}".format(k)] = dflt["method"]
        st.session_state["_prev_{}".format(k)]  = dflt["method"]
        if dflt["value"] is not None:
            st.session_state["value_{}".format(k)] = to_display(
                dflt["method"], dflt["value"])
        else:
            st.session_state.pop("value_{}".format(k), None)
    st.session_state["_adjusted"] = False
    st.session_state.pop("_adj_result", None)
    st.session_state.pop("_adj_overrides", None)
    for k in _COMMENTARY_KEYS:
        st.session_state.pop(k, None)


def _collect_state():
    """Read the current control values into {line: (method, display_val)}."""
    state = {}
    for line in LINE_DEFAULTS:
        k = _LINE_KEYS[line]
        method = st.session_state["method_{}".format(k)]
        display_val = st.session_state.get("value_{}".format(k), 0.0)
        state[line] = (method, display_val)
    return state


# ---------------------------------------------------------------------------
# The forecast's figures: KPI tiles, chart and P&L table
# ---------------------------------------------------------------------------

def _figures(full_df, pnl_df, last_actual, forecast_periods):
    """Draw one forecast's KPI tiles, timeline chart and P&L table from the
    figures Python computed. The worked example and a live run draw theirs
    the same way."""
    _fcst_year = forecast_periods[0][:4]
    _h1_periods = sorted(
        full_df[
            (full_df["type"] == "actual")
            & (full_df["period"].str.startswith(_fcst_year))
        ]["period"].unique()
    )

    def _h1_sum(items):
        return float(full_df[
            (full_df["type"] == "actual")
            & (full_df["line_item"].isin(items))
            & (full_df["period"].isin(_h1_periods))
        ]["value"].sum())

    _h1_rev = _h1_sum(REVENUE_ITEMS)
    _h1_gp = _h1_rev - _h1_sum(COGS_ITEMS)
    _h1_ebit = _h1_gp - _h1_sum(OPEX_ITEMS)

    rev_total = float(pnl_df[pnl_df["line"] == "Revenue"]["total"].iloc[0])
    gp_total = float(pnl_df[pnl_df["line"] == "Gross Profit"]["total"].iloc[0])
    ebit_total = float(
        pnl_df[pnl_df["line"] == "Operating Profit (EBIT)"]["total"].iloc[0]
    )

    st.markdown(
        _kpi_row_html("H1 {} actuals".format(_fcst_year), [
            ("Revenue",
             "{}{:,.0f}".format(CURRENCY_SYMBOL, _h1_rev), ""),
            ("Gross Profit",
             "{}{:,.0f}".format(CURRENCY_SYMBOL, _h1_gp),
             '<span style="color:#898781">{:.1%} margin</span>'.format(
                 _h1_gp / _h1_rev)),
            ("EBIT",
             "{}{:,.0f}".format(CURRENCY_SYMBOL, _h1_ebit),
             '<span style="color:#898781">{:.1%} margin</span>'.format(
                 _h1_ebit / _h1_rev)),
        ]),
        unsafe_allow_html=True,
    )

    _rev_delta = _hoh_badge(rev_total, _h1_rev)
    _gp_sub = '{:.1%} margin'.format(gp_total / rev_total)
    _gp_delta = _hoh_badge(gp_total, _h1_gp)
    if _gp_delta:
        _gp_sub = ('<span style="color:#898781">{}</span>'
                   '<br>{}').format(_gp_sub, _gp_delta)
    _ebit_sub = '{:.1%} margin'.format(ebit_total / rev_total)
    _ebit_delta = _hoh_badge(ebit_total, _h1_ebit)
    if _ebit_delta:
        _ebit_sub = ('<span style="color:#898781">{}</span>'
                     '<br>{}').format(_ebit_sub, _ebit_delta)

    st.markdown(
        _kpi_row_html("H2 {} forecast".format(_fcst_year), [
            ("Revenue",
             "{}{:,.0f}".format(CURRENCY_SYMBOL, rev_total),
             _rev_delta),
            ("Gross Profit",
             "{}{:,.0f}".format(CURRENCY_SYMBOL, gp_total),
             _gp_sub),
            ("EBIT",
             "{}{:,.0f}".format(CURRENCY_SYMBOL, ebit_total),
             _ebit_sub),
        ]),
        unsafe_allow_html=True,
    )

    # ---- Chart ------------------------------------------------------------

    st.markdown("#### Revenue and EBIT Timeline")

    fig = build_forecast_chart(full_df, last_actual, forecast_periods)
    st.pyplot(fig)
    plt.close(fig)

    # ---- P&L table --------------------------------------------------------

    st.markdown("#### P&L Summary")
    st.caption("All figures in EUR thousands.")

    st.markdown(
        _build_pnl_html(pnl_df, full_df, forecast_periods),
        unsafe_allow_html=True,
    )


def _commentary_cards(text):
    """The commentary's sections as the kicker and callout cards."""
    for _header, _body in parse_sections(text).items():
        st.markdown(
            '<div class="sc-exp-kicker">{}</div>'
            '<div class="sc-exp-callout">{}</div>'.format(
                _header, section_to_html(_body)
            ),
            unsafe_allow_html=True,
        )


def _review_reasons(flags, stop_reason, tok_out, has_commentary):
    """Why the run needs a person's review, as "Human review recommended"
    lists it; empty when check_requires_review finds no reason."""
    if not check_requires_review(flags, stop_reason, tok_out, has_commentary):
        return []
    reasons = []
    if flags:
        reasons.append("{} data flag(s) raised".format(len(flags)))
    if stop_reason == "max_tokens":
        reasons.append("commentary was truncated")
    if has_commentary and tok_out < 200:
        reasons.append("unusually short commentary ({} tokens)".format(tok_out))
    return reasons


# ---------------------------------------------------------------------------
# Sign-off (after Project 6: the rule and its messages live in src/signoff.py)
# ---------------------------------------------------------------------------

# The sign-off that stands (a SignOff) and the result it was made for (a
# fingerprint); the reviewer name box, kept under a plain key as well, so the
# name survives a run with no section to draw; the SIGN box; the last refusal
_SIGNED_KEY = "_signoff"
_SIGNED_FOR_KEY = "_signoff_for"
_REVIEWER_KEY = "_signoff_reviewer"
_NAME_KEY = "_signoff_name"
_SIGN_KEY = "_signoff_sign"
_REFUSAL_KEY = "_signoff_refusal"

_SIGNING_MEANS = (
    "Signing says you have read the result against the figures above. The "
    "figures come from Python. This version does not check the numbers in the "
    "model's wording.")


def _same_overrides(a, b):
    """Two sets of driver overrides that give the same forecast: the same
    method on every line, and the same value."""
    a, b = a or {}, b or {}
    return a.keys() == b.keys() and all(
        a[line]["method"] == b[line]["method"] and math.isclose(
            float(a[line]["value"]), float(b[line]["value"]),
            rel_tol=1e-9, abs_tol=1e-12)
        for line in a)


def _inputs_changed():
    """The driver panel no longer matches the drivers of the forecast on
    screen: a driver changed and Re-forecast has not been pressed since."""
    if st.session_state.get("_adjusted") and "_adj_result" in st.session_state:
        shown = st.session_state.get("_adj_overrides")
    else:
        shown = build_overrides({
            line: (d["method"], to_display(d["method"], d["value"]))
            for line, d in _file_drivers().items()})
    return not _same_overrides(build_overrides(_collect_state()), shown)


def _result_fingerprint(pnl_df, drivers_df, flags):
    """The result a sign-off is for, as one hash: the commentary run, its
    text and token counts, and the forecast's figures, flags and driver
    table, as the live PDF prints them. None while there is no commentary
    on screen, so nothing to sign."""
    if "_commentary_text" not in st.session_state:
        return None
    drivers = [[row["line_item"], row["driver_type"],
                round(float(row["driver_value"]), 9), str(row.get("note", ""))]
               for _, row in drivers_df.iterrows()]
    text = json.dumps({
        "run": st.session_state.get("_commentary_run"),
        "commentary": st.session_state["_commentary_text"],
        "tokens": list(st.session_state["_commentary_cost"]),
        "forecast": forecast_fingerprint(pnl_df),
        "flags": list(flags),
        "drivers": drivers,
    }, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _standing_signoff(result):
    """The sign-off that stands for the result on screen, or None. One made
    for another result (a Re-forecast that changed the figures, or a new
    Write commentary) no longer applies: the name stays filled in and the
    SIGN box is cleared."""
    signed = st.session_state.get(_SIGNED_KEY)
    if signed is not None and st.session_state.get(_SIGNED_FOR_KEY) != result:
        del st.session_state[_SIGNED_KEY]
        del st.session_state[_SIGNED_FOR_KEY]
        st.session_state[_NAME_KEY] = signed.name
        st.session_state[_SIGN_KEY] = ""
        signed = None
    return signed


def _keep_name():
    st.session_state[_NAME_KEY] = st.session_state.get(_REVIEWER_KEY, "")


def _sign_off(result, run, outstanding):
    """The Sign off button (on_click, as in Project 6). The rule decides; the
    page keeps the sign-off and the result it was made for, and adds it to
    that run's session audit row."""
    if _inputs_changed():
        return    # a click after a driver changed: the button now waits
    signed, refusal = sign_off(
        st.session_state.get(_REVIEWER_KEY), st.session_state.get(_SIGN_KEY),
        already_signed=(_SIGNED_KEY in st.session_state
                        and st.session_state.get(_SIGNED_FOR_KEY) == result))
    if refusal:
        st.session_state[_REFUSAL_KEY] = refusal
        return
    st.session_state[_SIGNED_KEY] = signed
    st.session_state[_SIGNED_FOR_KEY] = result
    add_signoff(run, signed.record(outstanding))


def _pdf_button(pdf_bytes, signed, **layout):
    """The report download, labelled by the sign-off that stands: the DRAFT
    PDF, or the FINAL PDF once signed. Nothing when the PDF could not be
    built: its plain message shows under Downloads instead."""
    if pdf_bytes is None:
        return
    st.download_button(
        "Download the FINAL PDF" if signed is not None
        else "Download the DRAFT PDF", data=pdf_bytes,
        file_name="forecast_report.pdf",
        mime="application/pdf", **layout)


def _render_signoff(result, signed, outstanding, stale, pdf_bytes):
    """The Sign-off section, in Project 4's order: DRAFT with the boxes, the
    button and then the DRAFT PDF, or FINAL and read only, with the FINAL
    PDF before the scope note."""
    refusal = st.session_state.pop(_REFUSAL_KEY, None)
    st.markdown("#### Sign-off")
    st.markdown(_SIGNING_MEANS)

    if signed is not None:
        st.markdown("{}&nbsp; {}".format(
            status_chip_html("final"), html.escape(signed.line)),
            unsafe_allow_html=True)
        if refusal:
            st.warning(refusal)
        _pdf_button(pdf_bytes, signed)
        st.caption(SCOPE_NOTE)
        return

    st.markdown(status_chip_html("draft"), unsafe_allow_html=True)
    if outstanding:
        st.markdown("Outstanding before you sign:")
        st.markdown("\n".join("{}. {}".format(i, line) for i, line
                              in enumerate(outstanding, start=1)))
    else:
        st.markdown("Nothing is outstanding.")
    if _NAME_KEY in st.session_state:
        st.session_state[_REVIEWER_KEY] = st.session_state[_NAME_KEY]
    st.text_input("Reviewer name", key=_REVIEWER_KEY, on_change=_keep_name)
    st.text_input(WORD_LABEL, key=_SIGN_KEY, help=WORD_HELP)
    st.button("Sign off", key="_signoff_button", type="primary",
              on_click=_sign_off,
              args=(result, st.session_state.get("_commentary_run"), outstanding),
              disabled=stale)
    if stale:
        st.caption(STALE_CAPTION)
    st.caption(SCOPE_NOTE)
    if refusal:
        st.warning(refusal)
    _pdf_button(pdf_bytes, None)


# ---------------------------------------------------------------------------
# Session audit
# ---------------------------------------------------------------------------

# A driver's value prints in its method's own shape (lib/driver_menu.py);
# fixed_growth is the older name of growth_pct
_AUDIT_SHAPE = dict(METHOD_VALUE_SHAPE,
                    fixed_growth=METHOD_VALUE_SHAPE["growth_pct"])


def _audit_driver_line(driver):
    """One driver of a run in the session audit, as "line: method (value)":
    a percentage as 120.0%, an amount as 45,000. A schedule-driven line has
    no single value, so it prints none."""
    shape = _AUDIT_SHAPE.get(driver["method"])
    if shape == "pct":
        value = " ({:.1%})".format(driver["value"])
    elif shape == "currency":
        value = " ({:,.0f})".format(driver["value"])
    else:
        value = ""
    return "{}: {}{}".format(driver["line"], driver["method"], value)


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

st.markdown(inject_css(), unsafe_allow_html=True)
st.markdown(header_html(
    "Forecast",
    "The six-month forecast, from the driver behind each line to the model's "
    "commentary on it."),
    unsafe_allow_html=True)

_init_state()
_detect_method_changes()

# The tab bar sits under the banner, as on Project 6. The worked example is
# the first tab, open on arrival; everything a live run needs is inside
# "Run it yourself".
_tab_ex, _tab_run = st.tabs(["View a worked example", "Run it yourself"])

# ---- The worked example: the base forecast and its saved commentary -------

with _tab_ex:
    _ex_full, _ex_pnl, _, _, _ex_last, _ex_periods = _base_forecast()
    if forecast_fingerprint(_ex_pnl) == EXAMPLE["fingerprint"]:
        st.caption("Saved example (base forecast, default drivers).")
        _figures(_ex_full, _ex_pnl, _ex_last, _ex_periods)
        st.markdown("#### AI Commentary")
        _commentary_cards(EXAMPLE["commentary"])
        st.caption(format_cost(EXAMPLE["tokens_in"], EXAMPLE["tokens_out"]))
    else:
        st.info(
            "The saved example was made from the sample data, and this "
            "forecast is built from different data, so it is not shown. Run "
            "it yourself works on this data."
        )

# ---- Run it yourself: the drivers, the forecast and the live commentary ---

with _tab_run:
    st.caption(
        "Base forecast for Valencia Operations. Adjust the driver assumptions "
        "below and click Re-forecast to see your scenario."
    )

    # ---- Driver panel -----------------------------------------------------

    _CELL = '<div style="line-height:38px">{}</div>'

    with st.expander("Driver assumptions", expanded=True):
        hc1, hc2, hc3 = st.columns([3, 4, 3])
        hc1.markdown("**Line item**")
        hc2.markdown("**Driver method**")
        hc3.markdown("**Value**")

        file_drivers = _file_drivers()
        for line in LINE_DEFAULTS:
            k = _LINE_KEYS[line]
            method_key = "method_{}".format(k)
            value_key  = "value_{}".format(k)
            own = file_drivers[line]
            methods = ALLOWED_METHODS[line]
            if own["method"] not in methods:
                # The driver file's method, though the menu does not offer
                # it: the panel opens on what the base forecast uses
                methods = [own["method"]] + methods

            c1, c2, c3 = st.columns([3, 4, 3])

            with c1:
                st.markdown(_CELL.format(line), unsafe_allow_html=True)

            with c2:
                st.selectbox(
                    line,
                    options=methods,
                    format_func=lambda m: METHOD_LABEL[m],
                    key=method_key,
                    label_visibility="collapsed",
                )

            method = st.session_state[method_key]
            shape  = METHOD_VALUE_SHAPE[method]
            # On the file's own method the box goes down to the file's value,
            # so a value below the usual floor shows as the file gives it
            own_low = (to_display(method, own["value"])
                       if method == own["method"] and own["value"] is not None
                       else math.inf)

            with c3:
                if shape == "schedule":
                    schedule_kind = ("hiring" if method == "headcount_driven"
                                     else "customer")
                    st.markdown(
                        _CELL.format(
                            '<span style="color:#5191c4; font-style:italic;'
                            ' white-space:nowrap">'
                            "{} schedule</span>".format(schedule_kind)),
                        unsafe_allow_html=True,
                    )
                elif shape == "pct":
                    pct_floor = 0.0 if method == "margin_pct" else -50.0
                    st.number_input(
                        _VALUE_LABELS[method],
                        min_value=min(pct_floor, own_low),
                        step=0.5,
                        format="%.1f",
                        key=value_key,
                        label_visibility="collapsed",
                    )
                else:
                    st.number_input(
                        _VALUE_LABELS[method],
                        min_value=min(0.0, own_low),
                        step=1000.0,
                        format="%.0f",
                        key=value_key,
                        label_visibility="collapsed",
                    )

    # ---- Action buttons ---------------------------------------------------

    btn_l, btn_r, _ = st.columns([2, 2, 5])
    with btn_l:
        reforecast = st.button("Re-forecast", type="primary",
                               use_container_width=True)
    with btn_r:
        # on_click, so the reset runs before the driver boxes are drawn:
        # Streamlit refuses to change a box that is already on screen
        st.button("Reset defaults", on_click=_reset_to_defaults,
                  use_container_width=True)

    if reforecast:
        overrides = _file_values(build_overrides(_collect_state()))
        result = _adjusted_forecast(overrides)
        st.session_state["_adj_result"] = result
        st.session_state["_adj_overrides"] = overrides
        st.session_state["_adjusted"] = True

    # ---- Select which forecast to display ---------------------------------

    if st.session_state.get("_adjusted") and "_adj_result" in st.session_state:
        full_df, pnl_df, driver_detail, flags, last_actual, forecast_periods = (
            st.session_state["_adj_result"]
        )
        st.success("Showing adjusted forecast.")
    else:
        full_df, pnl_df, driver_detail, flags, last_actual, forecast_periods = (
            _base_forecast()
        )

    # ---- Performance summary, chart and P&L table -------------------------

    _figures(full_df, pnl_df, last_actual, forecast_periods)

    # ---- Operational Inputs -----------------------------------------------

    st.markdown("#### Operational Inputs")
    st.caption(
        "Source data for the schedule-based drivers. Personnel Cost is "
        "computed from the headcount plan; Marketing Spend from the customer "
        "acquisition targets."
    )

    _ld = _load_data()
    _headcount_df = _ld[3]
    _customer_df = _ld[4]

    _oi_left, _oi_right = st.columns(2)
    with _oi_left:
        st.markdown("**Headcount Schedule** (Personnel Cost)")
        _hc_display = _headcount_df.copy()
        _hc_display.columns = ["Period", "New Hires", "Attrition Rate",
                               "Cost / Head (Annual)"]
        _hc_display["Attrition Rate"] = _hc_display["Attrition Rate"].map(
            "{:.1%}".format)
        _hc_display["Cost / Head (Annual)"] = _hc_display[
            "Cost / Head (Annual)"].map("EUR {:,.0f}".format)
        st.dataframe(_hc_display, hide_index=True, use_container_width=True)
    with _oi_right:
        st.markdown("**Customer Acquisition Targets** (Marketing Spend)")
        _ct_display = _customer_df.copy()
        _ct_display.columns = ["Period", "New Customers", "CAC",
                               "Fixed Campaign"]
        _ct_display["CAC"] = _ct_display["CAC"].map("EUR {:,.0f}".format)
        _ct_display["Fixed Campaign"] = _ct_display["Fixed Campaign"].map(
            "EUR {:,.0f}".format)
        st.dataframe(_ct_display, hide_index=True, use_container_width=True)

    # ---- AI Commentary ----------------------------------------------------

    st.markdown("#### AI Commentary")
    st.write(
        "Run the model to narrate the forecast: a structured commentary that "
        "explains the numbers without touching them. One model call per click."
    )

    _fp = forecast_fingerprint(pnl_df)
    _stored_fp = st.session_state.get("_commentary_fp")

    if _stored_fp is not None and _stored_fp != _fp:
        for _k in _COMMENTARY_KEYS:
            st.session_state.pop(_k, None)

    _live_client = st.session_state.get("live_client")
    _has_commentary = "_commentary_text" in st.session_state

    if _has_commentary:
        _commentary_cards(st.session_state["_commentary_text"])
        _tok_in, _tok_out = st.session_state["_commentary_cost"]
        st.caption(format_cost(_tok_in, _tok_out))
    elif _live_client is not None:
        if st.button("Write commentary", type="primary"):
            with st.spinner("Generating commentary..."):
                try:
                    _overrides = (st.session_state.get("_adj_overrides")
                                  if st.session_state.get("_adjusted") else None)
                    _base_drivers = _load_data()[1]
                    _eff_drivers = _effective_drivers(_base_drivers, _overrides)
                    _sys_prompt, _usr_prompt = build_prompt(
                        full_df, pnl_df, driver_detail, _eff_drivers,
                        last_actual, forecast_periods, flags,
                    )
                    _resp = _live_client.messages.create(
                        model=MODEL,
                        max_tokens=MAX_TOKENS,
                        system=_sys_prompt,
                        messages=[{"role": "user", "content": _usr_prompt}],
                    )
                    _reply = (getattr(_resp.content[0], "text", "")
                              if _resp.content else "")
                    if not _reply.strip():
                        # A reply with no text: one plain line, no stack trace
                        st.error(model_failure_message("unreadable_reply"))
                    else:
                        st.session_state["_commentary_text"] = _reply
                        st.session_state["_commentary_cost"] = (
                            _resp.usage.input_tokens, _resp.usage.output_tokens,
                        )
                        st.session_state["_commentary_stop"] = _resp.stop_reason
                        st.session_state["_commentary_fp"] = _fp
                        _ah, _dh = compute_data_hashes()
                        _row = record_run(
                            eff_drivers_df=_eff_drivers,
                            fingerprint=_fp,
                            actuals_hash=_ah,
                            driver_hash=_dh,
                            flags=flags,
                            has_commentary=True,
                            tok_in=_resp.usage.input_tokens,
                            tok_out=_resp.usage.output_tokens,
                            stop_reason=_resp.stop_reason,
                            overrides=_overrides,
                        )
                        # The run a sign-off of this commentary belongs to
                        st.session_state["_commentary_run"] = _row["timestamp"]
                        st.rerun()
                except Exception as exc:
                    st.error(friendly_message(exc))
    else:
        st.info(
            "Paste your Anthropic API key in the sidebar to run a live "
            "commentary."
        )

    # ---- Review status ----------------------------------------------------

    _stop_reason = st.session_state.get("_commentary_stop")
    _cmnt_tok_out = st.session_state.get("_commentary_cost", (0, 0))[1]
    _reasons = _review_reasons(
        flags, _stop_reason, _cmnt_tok_out, _has_commentary,
    )

    if _reasons:
        st.markdown(
            '<div class="sc-exp-caution">'
            "Human review recommended: {}.</div>".format("; ".join(_reasons)),
            unsafe_allow_html=True,
        )

    # ---- Data Flags -------------------------------------------------------

    st.markdown("#### Data Flags")
    if flags:
        for _flag in flags:
            st.warning(_flag)
    else:
        st.success("No data flags raised.")

    # ---- Downloads --------------------------------------------------------

    st.markdown("#### Downloads")

    _cur_overrides = (st.session_state.get("_adj_overrides")
                      if st.session_state.get("_adjusted") else None)
    _dl_drivers = _effective_drivers(_load_data()[1], _cur_overrides)
    _dl_commentary = st.session_state.get("_commentary_text")
    _dl_tok = st.session_state.get("_commentary_cost", (0, 0))

    # The result on screen and the sign-off that stands for it, if any: the
    # PDF prints its status line, DRAFT or FINAL
    _result = _result_fingerprint(pnl_df, _dl_drivers, flags)
    _signed = _standing_signoff(_result)

    try:
        _pdf_bytes = build_pdf_bytes(
            full_df, pnl_df, _dl_drivers, flags,
            last_actual, forecast_periods,
            commentary=_dl_commentary,
            tok_in=_dl_tok[0], tok_out=_dl_tok[1],
            headcount_df=_headcount_df, customer_df=_customer_df,
            status_line=pdf_status_line(_signed),
        )
    except Exception as exc:
        # A PDF that cannot be built must not take the CSV download with it
        _pdf_bytes = None
        st.error("The PDF report could not be built. " + friendly_message(exc))
    _csv_bytes = build_csv_bytes(pnl_df)

    # With commentary to sign, the PDF button sits in the Sign-off section
    # below. Before that there is no section, and the DRAFT PDF sits here: its
    # column is wider, so "Download the DRAFT PDF" sits on one line. The
    # CSV's column keeps its width.
    if _result is None and _pdf_bytes is not None:
        _dc_pdf, _dc_csv, _ = st.columns([3, 2, 4])
        with _dc_pdf:
            _pdf_button(_pdf_bytes, _signed, use_container_width=True)
    else:
        _dc_csv, _ = st.columns([2, 7])
    with _dc_csv:
        st.download_button(
            "Download CSV", data=_csv_bytes,
            file_name="forecast_pnl.csv",
            mime="text/csv",
            use_container_width=True,
        )

    # ---- Flags (if any) ---------------------------------------------------

    if flags:
        with st.expander("Engine flags ({})".format(len(flags))):
            for f in flags:
                st.write("- {}".format(f))

    # ---- Sign-off (only once there is commentary to sign) -----------------

    if _result is not None:
        _render_signoff(
            _result, _signed,
            ["{}{}.".format(r[0].upper(), r[1:]) for r in _reasons],
            _inputs_changed(), _pdf_bytes)

    # ---- Session audit ----------------------------------------------------

    _runs = get_runs()
    with st.expander("Session audit ({} run{})".format(
            len(_runs), "" if len(_runs) == 1 else "s")):
        st.caption(
            "Session only. This audit trail is held in the server's session "
            "state and cleared when your session ends."
        )
        if not _runs:
            st.info("No commentary runs recorded yet.")
        for _run in _runs:
            st.markdown("---")
            st.markdown("**{}**".format(_run["timestamp"][:19].replace("T", " ")))
            st.text("\n".join(_audit_driver_line(_d)
                              for _d in _run["effective_drivers"]))
            _audit_cols = st.columns(3)
            _audit_cols[0].metric("Fingerprint", _run["fingerprint"])
            if _run["has_commentary"] and _run["cost"]:
                _audit_cols[1].metric(
                    "Tokens", "{:,}".format(
                        _run["tokens_in"] + _run["tokens_out"]))
                _audit_cols[2].metric(
                    "Cost (est.)", "EUR {:.4f}".format(_run["cost"]["eur"]))
            st.caption("Actuals hash: {}".format(_run["actuals_hash"][:30]))
            st.caption("Driver hash: {}".format(_run["driver_hash"][:30]))
            if _run["requires_review"]:
                st.warning("Review recommended")
            if _run.get("status") == FINAL:
                # The run's sign-off, in the rule's own signed line
                _row_signed = SignOff(_run["signed_off_by"], datetime.fromisoformat(
                    _run["signed_off_at"]))
                st.markdown("{}&nbsp; {}".format(
                    status_chip_html("final"), html.escape(_row_signed.line)),
                    unsafe_allow_html=True)
                if _run["acknowledged_at_sign_off"]:
                    st.caption("Acknowledged at sign-off: " + " ".join(
                        _run["acknowledged_at_sign_off"]))
