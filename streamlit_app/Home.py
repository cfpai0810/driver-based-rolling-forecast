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

import streamlit.components.v1 as components

from streamlit_app.lib.theme import inject_css, DARK_BLUE
from streamlit_app.lib.key_gate import render_key_gate
from streamlit_app.lib.governance_flow import governance_flow_svg


def _home_page():
    """Render the landing page content."""
    st.markdown(inject_css(), unsafe_allow_html=True)

    st.markdown(
        '<div class="sc-header">'
        '<h1>Driver-Based Rolling Forecast</h1>'
        '<p>A six-month P&amp;L forecast built from the drivers behind each '
        'line, with AI commentary that explains the numbers without touching '
        'them.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    components.html(governance_flow_svg(), height=220, scrolling=False)

    st.markdown("#### What this does")
    st.write(
        "FP&A teams build rolling forecasts by projecting each P&L line from "
        "its underlying driver: revenue from a seasonal growth rate, COGS from "
        "a margin percentage, personnel from a headcount plan, and so on. This "
        "tool automates that calculation and lets you adjust individual drivers "
        "to see how the forecast responds, then calls Claude to narrate the "
        "result in plain language.")
    st.write(
        "One principle holds the whole thing together: the language model reads "
        "the computed forecast and writes the commentary, a deterministic "
        "engine performs every calculation, and a person approves the output. "
        "The intelligence sits at the edges; the numbers in the middle are "
        "computed the way a spreadsheet would compute them, and never by the "
        "model.")

    st.markdown("#### The sample company")
    st.write(
        "Everything here runs on Valencia Operations, a synthetic company "
        "invented for the demo. Its five data files describe a full history of "
        "monthly actuals through mid-2026 and the drivers behind them, and the "
        "tool forecasts the second half of the year on top of that history. "
        "Because the company and its numbers are entirely fictional, nothing "
        "you do on this site touches real or personal information.")

    DATA_DIR = ROOT / "data"
    expected = [
        "actuals_ytd.csv", "driver_table.csv", "operational_actuals.csv",
        "headcount_schedule.csv", "customer_targets.csv",
    ]
    present = [f for f in expected if (DATA_DIR / f).exists()]
    if len(present) == len(expected):
        st.success(
            f"Sample dataset loaded, {len(present)} of {len(expected)} files "
            "present. All figures on this site are illustrative.")
    else:
        missing = [f for f in expected if f not in present]
        st.warning(
            "The sample data is incomplete. Missing: " + ", ".join(missing) +
            ". The tool pages need these files in the project's data folder.")

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
            "tokens, a single run is well under one US cent in practice.")
        st.caption(
            "Your key is used only for your session and is not stored by this "
            "site. On the web the data stays sample-only; to work on your own "
            "numbers, run the project locally from GitHub.")

    st.markdown("#### Where to start")
    st.write(
        "If you want the reasoning first, read How the model works next; it "
        "explains what each driver is and how the forecast is built. If you "
        "would rather try it, open Forecast from the sidebar. The tool shows a "
        "worked example without a key, or you can paste your own Anthropic key "
        "to run a live analysis with AI commentary.")

    st.divider()
    st.caption("Sample data only. All figures are illustrative.")


st.set_page_config(
    page_title="Driver-Based Rolling Forecast",
    page_icon="•",
    layout="centered",
    initial_sidebar_state="expanded",
)

PAGES_DIR = Path(__file__).resolve().parent / "pages"

client = render_key_gate()
st.session_state["live_client"] = client

pg = st.navigation([
    st.Page(_home_page, title="Home", icon=":material/home:"),
    st.Page(str(PAGES_DIR / "how_the_model_works.py"),
            title="How the Model Works", icon=":material/menu_book:"),
    st.Page(str(PAGES_DIR / "forecast.py"),
            title="Forecast", icon=":material/trending_up:"),
    st.Page(str(PAGES_DIR / "your_own_data.py"),
            title="Your Own Data", icon=":material/upload_file:"),
    st.Page(str(PAGES_DIR / "how_its_built.py"),
            title="How It's Built", icon=":material/build:"),
])

pg.run()
