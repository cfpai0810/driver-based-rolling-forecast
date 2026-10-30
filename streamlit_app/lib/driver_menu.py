# =============================================================================
# lib/driver_menu.py -- curated driver-method menu for the driver-adjust surface
# =============================================================================
# For each P&L line, the default driver (from the sample driver_table.csv) and
# the methods a user may switch it to. This is the contract the driver-adjust
# UI consumes. The panel opens on the driver file the page loads
# (config.DRIVER_FILE); LINE_DEFAULTS is only the fallback for a line that
# file does not list.
#
# Rules:
#   - Each line's default method is first in its allowed list. A driver file
#     method that a line's list does not offer goes first in that line's
#     options on the page, so the panel opens on what the forecast uses.
#   - headcount_driven and cac_driven appear ONLY on their native lines
#     (Personnel Cost, Marketing Spend). No other line can switch INTO them.
#     This mirrors the engine guard in step2_forecast_engine.py.
#   - fixed_growth is the older name of growth_pct (month-on-month growth),
#     computed the same way. It is in no menu: a driver file line on
#     fixed_growth opens in the panel as growth_pct, with the file's value.
# =============================================================================

LINE_DEFAULTS = {
    "Revenue":           {"method": "seasonal_yoy",     "value": 0.12},
    "COGS":              {"method": "margin_pct",       "value": 0.418},
    "Personnel Cost":    {"method": "headcount_driven", "value": None},
    "Marketing Spend":   {"method": "cac_driven",       "value": None},
    "IT Infrastructure": {"method": "fixed",            "value": 45000.0},
    "R&D Expense":       {"method": "growth_pct",       "value": 0.06},
}

ALLOWED_METHODS = {
    "Revenue":           ["seasonal_yoy", "growth_pct"],
    "COGS":              ["margin_pct", "growth_pct", "fixed"],
    "Personnel Cost":    ["headcount_driven", "fixed", "growth_pct"],
    "Marketing Spend":   ["cac_driven", "fixed", "growth_pct"],
    "IT Infrastructure": ["fixed", "growth_pct"],
    "R&D Expense":       ["growth_pct", "fixed"],
}

# What kind of scalar input each method needs, so the UI knows what to render.
#   pct:      a percentage (0.12 means 12%)
#   currency: an absolute currency amount (e.g. 45000)
#   schedule: no scalar value; the line is driven by its auxiliary data file,
#             so the value input is hidden when this method is active
METHOD_VALUE_SHAPE = {
    "seasonal_yoy":     "pct",
    "growth_pct":       "pct",
    "margin_pct":       "pct",
    "fixed":            "currency",
    "headcount_driven": "schedule",
    "cac_driven":       "schedule",
}

METHOD_LABEL = {
    "seasonal_yoy":     "Seasonal YoY growth",
    "growth_pct":       "Month-on-month growth",
    "margin_pct":       "Margin % of revenue",
    "fixed":            "Fixed amount",
    "headcount_driven": "Headcount schedule",
    "cac_driven":       "Customer acquisition schedule",
}
