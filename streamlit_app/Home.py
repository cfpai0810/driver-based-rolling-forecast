# =============================================================================
# Home.py: the app shell and landing page (Streamlit entry point)
# =============================================================================
# Run locally: streamlit run streamlit_app/Home.py
# Streamlit >= 1.36 uses st.navigation + st.Page for multipage apps.
# =============================================================================

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit_app.lib.theme import inject_css, header_html
from streamlit_app.lib.key_gate import render_key_gate


def _home_page():
    """Render the landing page content."""
    st.markdown(inject_css(), unsafe_allow_html=True)

    st.markdown(header_html(
        "Driver-Based Rolling Forecast",
        "A six-month P&L forecast built from the drivers behind each line, "
        "with AI commentary that explains the numbers without touching them."),
        unsafe_allow_html=True)

    # The committed worked example needs no key: it is the "View a worked
    # example" tab on the Forecast page, its first tab, open on arrival
    if st.button("See the worked example"):
        st.switch_page(FORECAST_PAGE)

    st.markdown("#### What it does")
    st.markdown(
        "- Reads eighteen months of actuals to June 2026 and the driver behind "
        "each of the six forecast lines, with the hiring plan and the customer "
        "targets behind two of them.\n"
        "- Forecasts the second half of the year line by line from those "
        "drivers, and lets you change the driver of any line and re-forecast.\n"
        "- Writes commentary on the result with the model (Claude, via the "
        "Anthropic API) and your own key.\n"
        "- Produces a PDF report and a CSV of the P&L.")

    st.markdown("#### The governance promise")
    st.markdown(
        "- **Python forecasts.** Every figure in the tiles, the chart and the "
        "tables is calculated in code, never by the model.\n"
        "- **A rule marks for review.** Whether the output needs scrutiny is "
        "decided by rules.\n"
        "- **The model narrates.** It writes about the calculated figures and "
        "cannot change them. This version does not check the numbers in its "
        "wording.\n"
        "- **A person reviews.** This version has no sign-off step on the web, so "
        "nothing here is signed or final.")

    st.markdown("#### Pages")
    st.page_link(HOW_MODEL_PAGE, label="How the model works: each line's driver, "
                 "seasonal revenue and the lines you cannot change")
    st.page_link(FORECAST_PAGE, label="Forecast: a worked example, and a forecast "
                 "you re-run with your own drivers")
    st.page_link(OWN_DATA_PAGE, label="Your own data: the five CSV files and how "
                 "to run the project locally")
    st.page_link(HOW_BUILT_PAGE, label="How it's built: the governance, the "
                 "pipeline, the tests and the audit trail")

    with st.expander("Using your own API key"):
        st.write(
            "The worked example on the forecast page is free and needs no key. "
            "To run a live forecast with AI commentary, you supply your own "
            "Anthropic API key, and each run bills your Anthropic account "
            "directly. This is not a free AI service; it is your key and your "
            "usage.")
        st.write(
            "To get a key, sign up at the Anthropic Console "
            "(console.anthropic.com), add a payment method under Settings, then "
            "open Settings and API keys and create a key. The key is shown "
            "once, so copy it when it is created. Paste it into the sidebar "
            "here to run a live analysis.")
        st.write(
            "What it costs. Each run makes one short call to Claude Sonnet to "
            "narrate the forecast. At Sonnet's current rate of about three US "
            "dollars per million input tokens and fifteen per million output "
            "tokens, a single run costs about 1.4 US cents: the worked "
            "example used 1,742 input and 612 output tokens.")
        st.caption(
            "Your key is used only for your session and is not stored by this "
            "site. On the web the data stays sample-only; to work on your own "
            "numbers, run the project locally from GitHub.")

    st.divider()
    st.caption("Sample data only: Valencia Operations is a fictional company. "
               "All figures are illustrative.")

    DATA_DIR = ROOT / "data"
    expected = [
        "actuals_ytd.csv", "driver_table.csv", "operational_actuals.csv",
        "headcount_schedule.csv", "customer_targets.csv",
    ]
    missing = [f for f in expected if not (DATA_DIR / f).exists()]
    if missing:
        st.warning(
            "The sample data is incomplete. Missing: " + ", ".join(missing) +
            ". The tool pages need these files in the project's data folder.")


st.set_page_config(
    page_title="Driver-Based Rolling Forecast",
    page_icon=":material/trending_up:",
    layout="centered",
    initial_sidebar_state="auto",
)

PAGES_DIR = Path(__file__).resolve().parent / "pages"

client = render_key_gate()
st.session_state["live_client"] = client

# Titles only: each page's address comes from its file name, which stays
HOW_MODEL_PAGE = st.Page(str(PAGES_DIR / "how_the_model_works.py"),
                         title="How the model works", icon=":material/menu_book:")
FORECAST_PAGE = st.Page(str(PAGES_DIR / "forecast.py"),
                        title="Forecast", icon=":material/trending_up:")
OWN_DATA_PAGE = st.Page(str(PAGES_DIR / "your_own_data.py"),
                        title="Your own data", icon=":material/upload_file:")
HOW_BUILT_PAGE = st.Page(str(PAGES_DIR / "how_its_built.py"),
                         title="How it's built", icon=":material/build:")

pg = st.navigation([
    st.Page(_home_page, title="Home", icon=":material/home:"),
    HOW_MODEL_PAGE,
    FORECAST_PAGE,
    OWN_DATA_PAGE,
    HOW_BUILT_PAGE,
])

pg.run()
