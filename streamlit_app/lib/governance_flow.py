# =============================================================================
# lib/governance_flow.py -- the signature governance diagram
# =============================================================================
# Five-stage flow showing who owns each step of a forecast run. A person opens
# and closes every run; the model works only in between and never touches a
# figure. Colour encodes ownership: person (dark blue), model for language
# (purple), deterministic engine for numbers (green).
# =============================================================================

from streamlit_app.lib.theme import (
    DARK_BLUE, MID_BLUE, LIGHT_BLUE, GREEN, AMBER, MUTED, RULE, NEAR_WHITE,
)

PERSON    = DARK_BLUE
MODEL     = "#6B4FA8"
ENGINE    = GREEN
MODEL_BG  = "#F0ECF8"
ENGINE_BG = "#E8F3E9"
PERSON_BG = LIGHT_BLUE


def _box(x, w, stroke, bg, title, l1, l2, foot, foot_color):
    cx = x + w / 2
    return f"""
  <g>
    <rect x="{x}" y="66" width="{w}" height="128" rx="12"
          fill="{bg}" stroke="{stroke}" stroke-width="1.1"/>
    <text x="{cx}" y="96" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="12" font-weight="700" fill="{stroke}"
          letter-spacing="0.03em">{title}</text>
    <text x="{cx}" y="124" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="11.5" fill="{DARK_BLUE}">{l1}</text>
    <text x="{cx}" y="141" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="11.5" fill="{DARK_BLUE}">{l2}</text>
    <text x="{cx}" y="176" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="10" font-style="italic" fill="{foot_color}">{foot}</text>
  </g>"""


def _arrow(x):
    return (f'<line x1="{x}" y1="130" x2="{x+26}" y2="130" stroke="{MUTED}" '
            f'stroke-width="1.6" marker-end="url(#gv-arrow)"/>')


def governance_flow_svg():
    """Return the governance flow diagram as an inline SVG string."""
    boxes = (
        _box(14,  158, PERSON, PERSON_BG, "YOU SET DRIVERS",
             "Choose each line's", "method and value", "the person", PERSON) +
        _arrow(172) +
        _box(200, 170, ENGINE, ENGINE_BG, "PYTHON FORECASTS",
             "Deterministic code", "runs every P&amp;L line", "no model here", ENGINE) +
        _arrow(370) +
        _box(398, 158, MODEL, MODEL_BG, "THE MODEL NARRATES",
             "Commentary on the", "calculated figures", "words, not numbers", MODEL) +
        _arrow(556) +
        _box(584, 170, ENGINE, ENGINE_BG, "MARKED FOR REVIEW",
             "Rules flag when the", "output needs scrutiny", "deterministic", ENGINE) +
        _arrow(754) +
        _box(782, 124, PERSON, PERSON_BG, "YOU APPROVE",
             "You review and", "sign off the result", "the person", PERSON)
    )

    return f"""
<svg viewBox="0 0 920 292" width="100%" role="img"
     xmlns="http://www.w3.org/2000/svg"
     aria-label="How a forecast run is governed: you set each driver's method
     and value, deterministic code computes every P and L line with the model
     absent from the numbers, the model narrates the calculated figures, rules
     flag anything that needs scrutiny, and you review and approve the result.">
  <defs>
    <marker id="gv-arrow" viewBox="0 0 10 10" refX="8" refY="5"
            markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M2 1 L8 5 L2 9" fill="none" stroke="{MUTED}"
            stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
  </defs>

  <text x="460" y="28" text-anchor="middle" font-family="'Inter', sans-serif"
        font-size="13.5" font-weight="600" fill="{PERSON}">
    You set the drivers and approve the output. The model works only in between.
  </text>

  {boxes}

  <line x1="14" y1="228" x2="906" y2="228" stroke="{RULE}"
        stroke-width="1" stroke-dasharray="3 4"/>
  <text x="460" y="250" text-anchor="middle" font-family="'Inter', sans-serif"
        font-size="11" fill="{MUTED}">
    Every step is written to the audit record, so any run can be
    reconstructed afterwards.
  </text>

  <g font-family="'Inter', sans-serif" font-size="11">
    <rect x="220" y="270" width="11" height="11" rx="2" fill="{PERSON_BG}"
          stroke="{PERSON}"/>
    <text x="237" y="279" fill="{DARK_BLUE}">You</text>
    <rect x="286" y="270" width="11" height="11" rx="2" fill="{MODEL_BG}"
          stroke="{MODEL}"/>
    <text x="303" y="279" fill="{DARK_BLUE}">The model, for language</text>
    <rect x="480" y="270" width="11" height="11" rx="2" fill="{ENGINE_BG}"
          stroke="{ENGINE}"/>
    <text x="497" y="279" fill="{DARK_BLUE}">Deterministic code, for numbers</text>
  </g>
</svg>
"""
