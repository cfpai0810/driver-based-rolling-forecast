# =============================================================================
# pages/forecast.py -- base and adjusted forecast display (Phases 3+4+5+6)
# =============================================================================
# On page load, shows the base forecast. The driver panel lets the user
# change any of the six line drivers, then click "Re-forecast" to recompute.
# "Reset to defaults" returns to the base forecast.
#
# Widget-state design (the known-hard part):
#   Every control has a stable key; its value lives in st.session_state.
#   The "Re-forecast" button reads the current state, builds overrides, and
#   runs the engine. No widget relies on value= to carry state across reruns;
#   method-selector changes trigger a rerun for relabelling, and the value
#   inputs survive that rerun via their keys.
# =============================================================================

import sys
from pathlib import Path

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit_app.lib.theme import inject_css
from streamlit_app.lib.driver_menu import (
    LINE_DEFAULTS, ALLOWED_METHODS, METHOD_LABEL, METHOD_VALUE_SHAPE,
)
from streamlit_app.lib.driver_controls import to_display, build_overrides
from streamlit_app.lib.charts import build_forecast_chart
from streamlit_app.lib.commentary import (
    forecast_fingerprint, parse_sections, section_to_html,
)
from streamlit_app.lib.cost import format_cost
from streamlit_app.lib.errors import friendly_message
from streamlit_app.lib.audit import record_run, get_runs
from streamlit_app.lib.example_run import EXAMPLE
from src.step3_ai_engine import build_prompt
from src.step4_output_writer import (
    build_pdf_bytes, build_csv_bytes, compute_data_hashes, check_requires_review,
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


def _effective_drivers(base_drivers_df, overrides):
    """Return a drivers_df reflecting any user overrides, so build_prompt
    and the PDF driver table show the adjusted assumptions rather than the
    CSV defaults."""
    if not overrides:
        return base_drivers_df
    df = base_drivers_df.copy()
    for line, ov in overrides.items():
        mask = df["line_item"] == line
        if mask.any():
            df.loc[mask, "driver_type"] = ov["method"]
            df.loc[mask, "driver_value"] = ov["value"]
    return df


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
            sub_html = ('<div style="font-size:0.78rem;margin-top:2px">'
                        '{}</div>').format(sub)
        cards.append(
            '<div style="flex:1;background:{};border-left:4px solid {};'
            'border-radius:8px;padding:14px 18px">'
            '<div style="font-size:0.72rem;color:{};font-weight:600;'
            'letter-spacing:0.05em;text-transform:uppercase">{}</div>'
            '<div style="font-size:1.4rem;font-weight:700;color:{};'
            'margin-top:4px">{}</div>'
            '{}</div>'.format(LIGHT_BLUE, DARK_BLUE, MUTED, label,
                              DARK_BLUE, value, sub_html)
        )
    return (
        '<div style="margin-bottom:10px">'
        '<div style="font-size:0.82rem;font-weight:600;color:{};'
        'margin-bottom:8px">{}</div>'
        '<div style="display:flex;gap:12px">{}</div>'
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


def _init_state():
    """Seed session state with defaults on first load."""
    if "_drv_init" in st.session_state:
        return
    for line, dflt in LINE_DEFAULTS.items():
        k = _LINE_KEYS[line]
        st.session_state["method_{}".format(k)] = dflt["method"]
        st.session_state["_prev_{}".format(k)]  = dflt["method"]
        if dflt["value"] is not None:
            st.session_state["value_{}".format(k)] = to_display(
                dflt["method"], dflt["value"])
    st.session_state["_drv_init"] = True
    st.session_state["_adjusted"] = False


def _detect_method_changes():
    """If a method selector changed since the last render, set a sensible
    default value for the new method before widgets render."""
    for line, dflt in LINE_DEFAULTS.items():
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
    for line, dflt in LINE_DEFAULTS.items():
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
    for k in ("_commentary_text", "_commentary_cost", "_commentary_fp",
              "_commentary_stop"):
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
# Page layout
# ---------------------------------------------------------------------------

st.markdown(inject_css(), unsafe_allow_html=True)
st.markdown("### Forecast")
st.caption(
    "Base forecast for Valencia Operations. Adjust the driver assumptions "
    "below and click Re-forecast to see your scenario."
)

_init_state()
_detect_method_changes()

# ---- Driver panel ---------------------------------------------------------

_CELL = '<div style="line-height:38px">{}</div>'

with st.expander("Driver assumptions", expanded=True):
    hc1, hc2, hc3 = st.columns([3, 4, 3])
    hc1.markdown("**Line item**")
    hc2.markdown("**Driver method**")
    hc3.markdown("**Value**")

    for line in LINE_DEFAULTS:
        k = _LINE_KEYS[line]
        method_key = "method_{}".format(k)
        value_key  = "value_{}".format(k)
        methods = ALLOWED_METHODS[line]

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
                    min_value=pct_floor,
                    step=0.5,
                    format="%.1f",
                    key=value_key,
                    label_visibility="collapsed",
                )
            else:
                st.number_input(
                    _VALUE_LABELS[method],
                    min_value=0.0,
                    step=1000.0,
                    format="%.0f",
                    key=value_key,
                    label_visibility="collapsed",
                )

# ---- Action buttons -------------------------------------------------------

btn_l, btn_r, _ = st.columns([2, 2, 5])
with btn_l:
    reforecast = st.button("Re-forecast", type="primary", use_container_width=True)
with btn_r:
    reset = st.button("Reset defaults", use_container_width=True)

if reset:
    _reset_to_defaults()
    st.rerun()

if reforecast:
    overrides = build_overrides(_collect_state())
    result = _adjusted_forecast(overrides)
    st.session_state["_adj_result"] = result
    st.session_state["_adj_overrides"] = overrides
    st.session_state["_adjusted"] = True

# ---- Select which forecast to display -------------------------------------

if st.session_state.get("_adjusted") and "_adj_result" in st.session_state:
    full_df, pnl_df, driver_detail, flags, last_actual, forecast_periods = (
        st.session_state["_adj_result"]
    )
    st.success("Showing adjusted forecast.")
else:
    full_df, pnl_df, driver_detail, flags, last_actual, forecast_periods = (
        _base_forecast()
    )

# ---- Performance summary --------------------------------------------------

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

# ---- Chart ----------------------------------------------------------------

st.markdown("#### Revenue and EBIT Timeline")

fig = build_forecast_chart(full_df, last_actual, forecast_periods)
st.pyplot(fig)
plt.close(fig)

# ---- P&L table ------------------------------------------------------------

st.markdown("#### P&L Summary")
st.caption("All figures in EUR thousands.")

st.markdown(
    _build_pnl_html(pnl_df, full_df, forecast_periods),
    unsafe_allow_html=True,
)

# ---- Operational Inputs ---------------------------------------------------

st.markdown("#### Operational Inputs")
st.caption(
    "Source data for the schedule-based drivers. Personnel Cost is computed "
    "from the headcount plan; Marketing Spend from the customer acquisition "
    "targets."
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

# ---- AI Commentary --------------------------------------------------------

st.markdown("#### AI Commentary")
st.write(
    "Run the model to narrate the forecast: a structured commentary that "
    "explains the numbers without touching them. One model call per click."
)

_fp = forecast_fingerprint(pnl_df)
_stored_fp = st.session_state.get("_commentary_fp")

if _stored_fp is not None and _stored_fp != _fp:
    for _k in ("_commentary_text", "_commentary_cost", "_commentary_fp",
               "_commentary_stop"):
        st.session_state.pop(_k, None)

_live_client = st.session_state.get("live_client")
_has_commentary = "_commentary_text" in st.session_state

_tab_run, _tab_ex = st.tabs(["Run it yourself", "View a worked example"])

with _tab_run:
    if _has_commentary:
        _sections = parse_sections(st.session_state["_commentary_text"])
        for _header, _body in _sections.items():
            st.markdown(
                '<div class="sc-exp-kicker">{}</div>'
                '<div class="sc-exp-callout">{}</div>'.format(
                    _header, section_to_html(_body)
                ),
                unsafe_allow_html=True,
            )
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
                    st.session_state["_commentary_text"] = _resp.content[0].text
                    st.session_state["_commentary_cost"] = (
                        _resp.usage.input_tokens, _resp.usage.output_tokens,
                    )
                    st.session_state["_commentary_stop"] = _resp.stop_reason
                    st.session_state["_commentary_fp"] = _fp
                    _ah, _dh = compute_data_hashes()
                    record_run(
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
                    st.rerun()
                except Exception as exc:
                    st.error(friendly_message(exc))
    else:
        st.info(
            "Paste your Anthropic API key in the sidebar to run a live "
            "commentary."
        )

with _tab_ex:
    if _fp == EXAMPLE["fingerprint"]:
        st.caption("Saved example (base forecast, default drivers).")
        _ex_sections = parse_sections(EXAMPLE["commentary"])
        for _header, _body in _ex_sections.items():
            st.markdown(
                '<div class="sc-exp-kicker">{}</div>'
                '<div class="sc-exp-callout">{}</div>'.format(
                    _header, section_to_html(_body)
                ),
                unsafe_allow_html=True,
            )
        st.caption(format_cost(EXAMPLE["tokens_in"], EXAMPLE["tokens_out"]))
    else:
        st.info(
            "The saved example matches the base forecast only. Reset to "
            "defaults to see it, or paste your API key in the sidebar to "
            "generate commentary for this adjusted forecast."
        )

# ---- Review status --------------------------------------------------------

_stop_reason = st.session_state.get("_commentary_stop")
_cmnt_tok_out = st.session_state.get("_commentary_cost", (0, 0))[1]
_needs_review = check_requires_review(
    flags, _stop_reason, _cmnt_tok_out, _has_commentary,
)

if _needs_review:
    _reasons = []
    if flags:
        _reasons.append("{} data flag(s) raised".format(len(flags)))
    if _stop_reason == "max_tokens":
        _reasons.append("commentary was truncated")
    if _has_commentary and _cmnt_tok_out < 200:
        _reasons.append(
            "unusually short commentary ({} tokens)".format(_cmnt_tok_out))
    st.markdown(
        '<div class="sc-exp-caution">'
        "Human review recommended: {}.</div>".format("; ".join(_reasons)),
        unsafe_allow_html=True,
    )

# ---- Data Flags -----------------------------------------------------------

st.markdown("#### Data Flags")
if flags:
    for _flag in flags:
        st.warning(_flag)
else:
    st.success("No data flags raised.")

# ---- Downloads ------------------------------------------------------------

st.markdown("#### Downloads")

_cur_overrides = (st.session_state.get("_adj_overrides")
                  if st.session_state.get("_adjusted") else None)
_dl_drivers = _effective_drivers(_load_data()[1], _cur_overrides)
_dl_commentary = st.session_state.get("_commentary_text")
_dl_tok = st.session_state.get("_commentary_cost", (0, 0))

_pdf_bytes = build_pdf_bytes(
    full_df, pnl_df, _dl_drivers, flags,
    last_actual, forecast_periods,
    commentary=_dl_commentary,
    tok_in=_dl_tok[0], tok_out=_dl_tok[1],
    headcount_df=_headcount_df, customer_df=_customer_df,
)
_csv_bytes = build_csv_bytes(pnl_df)

_dc1, _dc2, _ = st.columns([2, 2, 5])
with _dc1:
    st.download_button(
        "Download PDF", data=_pdf_bytes,
        file_name="forecast_report.pdf",
        mime="application/pdf",
        use_container_width=True,
    )
with _dc2:
    st.download_button(
        "Download CSV", data=_csv_bytes,
        file_name="forecast_pnl.csv",
        mime="text/csv",
        use_container_width=True,
    )

# ---- Flags (if any) -------------------------------------------------------

if flags:
    with st.expander("Engine flags ({})".format(len(flags))):
        for f in flags:
            st.write("- {}".format(f))

# ---- Session audit --------------------------------------------------------

_runs = get_runs()
with st.expander("Session audit ({} run{})".format(
        len(_runs), "" if len(_runs) == 1 else "s")):
    st.caption(
        "Session only. This audit trail is held in your browser and cleared "
        "when the tab closes. It is never stored on any server."
    )
    if not _runs:
        st.info("No commentary runs recorded yet.")
    for _run in _runs:
        st.markdown("---")
        st.markdown("**{}**".format(_run["timestamp"][:19].replace("T", " ")))
        _drv_lines = []
        for _d in _run["effective_drivers"]:
            _drv_lines.append("{}: {} ({})".format(
                _d["line"], _d["method"],
                "{:.1%}".format(_d["value"]) if _d["value"] < 1
                else "{:,.0f}".format(_d["value"]),
            ))
        st.text("\n".join(_drv_lines))
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
