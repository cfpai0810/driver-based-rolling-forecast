# =============================================================================
# lib/pipeline_flow.py: the pipeline diagram
# =============================================================================
# Same visual grammar as governance_flow.py: purple = the model (language
# only), green = deterministic engine, dark blue = data/person. Shows the AI
# boundary: the model appears in exactly one of five stages; everything
# numeric is deterministic. Drawn in HTML by lib/flow_diagram.py, so it reads
# on a phone.
# =============================================================================

from streamlit_app.lib.flow_diagram import Role, Stage, flow_html
from streamlit_app.lib.governance_flow import ENGINE, MODEL
from streamlit_app.lib.theme import DARK_BLUE, LIGHT_BLUE

DATA = Role(DARK_BLUE, LIGHT_BLUE)

LABEL = ("The pipeline: a deterministic data stage loads five CSV files and finds "
         "the forecast horizon; a deterministic forecast stage applies driver-based "
         "calculations to every P and L line; a deterministic validate stage checks "
         "bounds and flags anomalies; the model narrates the computed figures in a "
         "commentary stage; and a deterministic output stage writes the PDF, CSV, "
         "and audit record. Only the commentary stage uses the model; everything "
         "numeric is deterministic.")

STAGES = (
    Stage("Data", "load five CSVs, find horizon", "deterministic", DATA),
    Stage("Forecast", "driver-based calc, build P&L", "deterministic", ENGINE),
    Stage("Validate", "check bounds, flag anomalies", "deterministic", ENGINE),
    Stage("Commentary", "narrate the computed figures", "model, language", MODEL),
    Stage("Output", "PDF, CSV, audit record", "deterministic", ENGINE),
)


def pipeline_flow_html():
    """Return the pipeline diagram as HTML for st.markdown."""
    return flow_html(
        LABEL, STAGES,
        heading="The model appears in one stage only. Everything numeric is "
                "deterministic.",
        note="The commentary stage is handed already-final figures. The model "
             "narrates; it does not calculate.",
        key=((MODEL, "Model, for language"),
             (ENGINE, "Deterministic code, for numbers")))
