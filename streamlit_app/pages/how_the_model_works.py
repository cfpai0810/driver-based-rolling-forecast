# =============================================================================
# pages/how_the_model_works.py: driver reference for the forecast model
# =============================================================================
# Explains how each P&L line is calculated, what driver controls it, and how
# the interactive controls on the Forecast page map to the engine. No API key
# needed.
# =============================================================================

import sys
from pathlib import Path

import streamlit as st
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit_app.lib.theme import inject_css, DARK_BLUE, MUTED
from config import CURRENCY_CODE

st.markdown(inject_css(), unsafe_allow_html=True)

st.markdown("### How the model works")
st.write(
    "The forecast is a driver-based model, which means every line of the "
    "profit and loss is produced by a specific formula rather than typed in by "
    "hand. Revenue comes from a seasonal growth rate, COGS from a margin, IT "
    "from a fixed monthly cost, and so on. The Forecast page lets you change "
    "any driver's method and value, and the engine recomputes the entire P&L "
    "when you click Re-forecast. Knowing what each driver is, and what units "
    "it takes, is the whole trick to getting a useful result, which is what "
    "the rest of this page is for.")

st.markdown("---")

# -- The sample company and horizon -------------------------------------------
st.markdown("#### The numbers behind it")
st.write(
    "Everything runs on Valencia Operations, a synthetic company built for the "
    "demo. It has a full history of monthly actuals running through June 2026, "
    "and the tool forecasts the six months from July to December on top of that "
    "history. That split matters when you read a result: the first half of the "
    "year is settled actuals that no driver change can touch, and the second "
    "half is the forecast your adjustments actually move. The P&L table "
    "stitches the two together, so you are always looking at actuals plus "
    "forecast, not a forecast floating on its own.")

st.markdown("---")

# -- P&L structure ------------------------------------------------------------
st.markdown("#### The P&L lines and their drivers")
st.write(
    "Each line below is controlled by one driver. The units column is the part "
    "worth reading closely, because most unexpected results come from a "
    "mismatch between what the driver expects and what you entered.")

lines = [
    {
        "P&L line": "Revenue",
        "Driver": "Seasonal YoY growth",
        "Units": "Fraction (e.g. 0.12 = 12%)",
        "Default": "0.12 (12% annual growth)",
    },
    {
        "P&L line": "COGS",
        "Driver": "Margin (% of Revenue)",
        "Units": "Fraction (e.g. 0.418 = 41.8%)",
        "Default": "0.418 (41.8% of revenue)",
    },
    {
        "P&L line": "Personnel Cost",
        "Driver": "Headcount schedule",
        "Units": "Driven by hiring plan CSV",
        "Default": "42 starting, +9 hires, 6 attrition",
    },
    {
        "P&L line": "Marketing Spend",
        "Driver": "Customer acquisition targets",
        "Units": "Driven by targets CSV",
        "Default": "320 customers, EUR 1,200 CAC",
    },
    {
        "P&L line": "IT Infrastructure",
        "Driver": "Fixed cost per month",
        "Units": "{} per month".format(CURRENCY_CODE),
        "Default": "45,000 per month",
    },
    {
        "P&L line": "R&D Expense",
        "Driver": "Monthly growth rate",
        "Units": "Fraction (e.g. 0.06 = 6%)",
        "Default": "0.06 (6% month on month)",
    },
]

st.dataframe(pd.DataFrame(lines), use_container_width=True, hide_index=True)

# -- Driver methods on the Forecast page --------------------------------------
st.markdown("---")
st.markdown("#### Changing drivers on the Forecast page")
st.write(
    "The driver panel on the Forecast page shows a method selector and a value "
    "input for each P&L line. When you change a method, the value input "
    "relabels itself to match the units that method expects. You can switch "
    "any line to a different method (for example, switching Revenue from "
    "seasonal YoY to a fixed monthly amount) and the engine will apply the "
    "new formula. Click Re-forecast to recompute the P&L with your changes, "
    "or Reset to defaults to return to the base forecast.")

st.write(
    "The available methods for each line are: seasonal YoY growth, margin "
    "percentage, fixed amount, and growth percentage. Not every method makes "
    "sense for every line (a margin on IT Infrastructure, for instance, "
    "would be unusual), but the engine will compute it if you ask. The "
    "defaults shown in the table above are the ones that match the sample "
    "company's actual driver structure.")

# -- How derived lines work ---------------------------------------------------
st.markdown("---")
st.markdown("#### The lines you cannot change directly")
st.write(
    "Three lines are not drivers at all. They are computed from the ones above, "
    "so you change them by changing their inputs rather than by naming them.")
st.write(
    "**Gross Profit** is Revenue minus COGS. It moves when you change Revenue "
    "or COGS, never on its own.")
st.write(
    "**Total OpEx** is the sum of Personnel Cost, Marketing Spend, IT "
    "Infrastructure, and R&D Expense.")
st.write(
    "**Operating Profit (EBIT)** is Gross Profit minus Total OpEx. It is the "
    "bottom line of the model and the figure the KPI metrics lead with, "
    "because it is where every driver change ultimately lands.")

# -- The seasonality model ----------------------------------------------------
st.markdown("---")
st.markdown("#### How seasonal revenue works")
st.write(
    "The seasonal YoY driver does not spread growth evenly across months. It "
    "reads the prior calendar year's monthly revenue to derive seasonal "
    "indices (how much each month deviates from the average), then applies "
    "the annual growth target through those indices. That is why July and "
    "August show lower revenue than November and December: the seasonal "
    "pattern from the prior year carries forward.")
st.info(
    "Revenue growth is the single highest-leverage driver in the model. A "
    "small change to the growth rate moves every downstream line (COGS "
    "tracks revenue, gross profit follows, EBIT follows gross profit), "
    "so it is worth getting right before adjusting anything else.")

# -- Marketing assumption -----------------------------------------------------
st.markdown("---")
st.markdown("#### One assumption worth knowing")
st.info(
    "Marketing Spend is driven by customer acquisition targets, but Revenue is "
    "modelled on its own seasonal trend, and the two are not linked in this "
    "model. Changing marketing spend does not change revenue. That is a real "
    "simplification, and the commentary flags it when it applies. A cut to "
    "marketing should be read as an upper bound on the profit benefit rather "
    "than the full picture.")

st.divider()
st.caption(
    "This page describes the sample model. Your own model may have different "
    "drivers and line items.")
