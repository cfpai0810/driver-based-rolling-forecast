# =============================================================================
# lib/example_run.py -- captured base-forecast commentary for keyless visitors
# =============================================================================
# Mirrors Project 4's pattern: a single EXAMPLE dict containing the four-
# section commentary produced on the default drivers (no overrides), so a
# visitor with no API key still sees a worked example.
#
# The fingerprint ties this commentary to the exact P&L it describes. When
# the forecast page detects that the current fingerprint matches, it shows
# this example; when it differs (because the user changed a driver), the
# page shows a fallback note instead.
# =============================================================================

EXAMPLE = {
    "fingerprint": "2a77f503a0a1f4b5",
    "tokens_in": 1742,
    "tokens_out": 612,
    "model": "claude-sonnet-4-6",
    "commentary": (
        "FORECAST OVERVIEW\n"
        "H2 2026 revenue for Valencia Operations is forecast at EUR 8,490,872, "
        "producing a gross profit of EUR 4,941,688 at a 58.2% gross margin. "
        "Total operating expenses of EUR 4,399,497 leave an operating profit "
        "of EUR 542,191, a 6.4% EBIT margin for the half. August is the "
        "weakest month at EUR 22,354 EBIT, driven by the seasonal revenue "
        "trough combining with steadily rising personnel and R&D costs. The "
        "trajectory improves through Q4 as seasonal indices lift revenue "
        "toward the December peak.\n"
        "\n"
        "DRIVER COMMENTARY\n"
        "**Revenue:** The 12% annual growth assumption applied to trailing "
        "twelve-month revenue of EUR 14,475,000 produces an annual target of "
        "EUR 16,212,000, spread across months using 2025 seasonality. The "
        "seasonal indices show a pronounced summer dip (July 0.920, August "
        "0.894) recovering into a strong Q4 (November 1.157, December 1.227). "
        "If the actual run rate through H1 was softer than the trailing twelve "
        "months imply, the 12% assumption may overstate the second half.\n"
        "\n"
        "**Personnel Cost:** Headcount grows from 42 to a peak of 46 in "
        "November before one net attrition brings it to 45 by December, with "
        "9 planned hires offset by 6 departures. At EUR 6,500 fully loaded "
        "cost per head per month, personnel rises from EUR 276,250 in July to "
        "EUR 299,000 in November. The risk sits in the hiring schedule: if "
        "any of the three September hires slip, the Q4 cost base falls but "
        "so does capacity.\n"
        "\n"
        "**Marketing Spend:** The plan targets 320 new customers across H2 at "
        "a flat EUR 1,200 CAC plus EUR 25,000 fixed campaign spend per month, "
        "totalling EUR 534,000. November carries the heaviest load at 70 new "
        "customers (EUR 109,000). The assumption that CAC holds flat at "
        "EUR 1,200 through a seasonal peak deserves scrutiny, since "
        "acquisition costs typically rise when competitors increase spend in "
        "the same period.\n"
        "\n"
        "**Other costs:** COGS tracks revenue at a fixed 41.8% margin, "
        "producing EUR 3,549,185 for the half. IT Infrastructure holds at "
        "EUR 45,000 per month (EUR 270,000 total), and R&D ramps at 6% month "
        "on month from EUR 267,120 to EUR 357,467, adding EUR 1,863,247 for "
        "the half. The R&D growth rate is the single largest contributor to "
        "OpEx acceleration and will compress EBIT further if revenue "
        "underperforms.\n"
        "\n"
        "KEY RISKS AND RECOMMENDATIONS\n"
        "- **The 12% revenue growth assumption is the highest-leverage "
        "variable.** A two-point miss to 10% would cut H2 revenue by roughly "
        "EUR 280,000 and, with COGS tracking proportionally, reduce EBIT by "
        "approximately EUR 163,000, nearly a third of the forecast operating "
        "profit.\n"
        "- **R&D expense at 6% month-on-month growth reaches EUR 357,467 by "
        "December**, more than doubling IT and approaching personnel cost. If "
        "the board revisits the approved ramp mid-half, the EBIT impact is "
        "immediate and material.\n"
        "- **Monitor August EBIT closely.** At EUR 22,354 it is the thinnest "
        "month in the forecast, and any negative variance on revenue or an "
        "early hire could push it to breakeven or below.\n"
        "\n"
        "DATA FLAGS\n"
        "No flags raised."
    ),
}
