# =============================================================================
# lib/governance_flow.py: the signature governance diagram
# =============================================================================
# Five-stage flow showing who owns each step of a forecast run. A person opens
# and closes every run; the model works only in between and never touches a
# figure. Colour encodes ownership: person (dark blue), model for language
# (purple), deterministic engine for numbers (green). Drawn in HTML by
# lib/flow_diagram.py, so it reads on a phone.
# =============================================================================

from streamlit_app.lib.flow_diagram import Role, Stage, flow_html
from streamlit_app.lib.theme import DARK_BLUE, GREEN, LIGHT_BLUE

PERSON = Role(DARK_BLUE, LIGHT_BLUE)
MODEL  = Role("#6B4FA8", "#F0ECF8")
ENGINE = Role(GREEN, "#E8F3E9")

LABEL = ("How a forecast run is governed: you set each driver's method and value, "
         "deterministic code computes every P and L line with the model absent from "
         "the numbers, the model narrates the calculated figures, rules flag "
         "anything that needs scrutiny, and you review and sign off the result.")

STAGES = (
    Stage("YOU SET DRIVERS", "Choose each line's method and value", "the person",
          PERSON),
    Stage("PYTHON FORECASTS", "Deterministic code runs every P&L line",
          "no model here", ENGINE),
    Stage("THE MODEL NARRATES", "Commentary on the calculated figures",
          "words, not numbers", MODEL),
    Stage("MARKED FOR REVIEW", "Rules flag when the output needs scrutiny",
          "deterministic", ENGINE),
    Stage("YOU SIGN OFF", "You review and sign off the result", "the person",
          PERSON),
)


def governance_flow_html():
    """Return the governance flow diagram as HTML for st.markdown."""
    return flow_html(
        LABEL, STAGES,
        heading="You set the drivers and sign off the output. The model works only "
                "in between.",
        note="Every step is written to the audit record, so any run can be "
             "reconstructed afterwards.",
        key=((PERSON, "You"), (MODEL, "The model, for language"),
             (ENGINE, "Deterministic code, for numbers")))
