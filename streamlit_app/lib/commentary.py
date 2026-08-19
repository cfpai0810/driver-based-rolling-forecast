# =============================================================================
# lib/commentary.py -- forecast fingerprint and commentary section parsing
# =============================================================================
# Pure functions, no Streamlit dependency, testable headless.
#
# forecast_fingerprint: deterministic hash of a P&L so the stale-clear knows
#     when the forecast changed since the commentary was written.
# parse_sections: split the four-section commentary into a dict.
# section_to_html: convert simple markdown (bold, bullets) to HTML for the
#     callout cards.
# =============================================================================

import hashlib
import json
import re


def forecast_fingerprint(pnl_df):
    """Deterministic fingerprint of a forecast's P&L figures.

    Two forecasts with different driver assumptions produce different P&L
    values, so their fingerprints differ. The same forecast always produces
    the same fingerprint.
    """
    numeric = pnl_df.drop(columns=["line"]).values.tolist()
    raw = json.dumps(numeric, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


_SECTION_HEADERS = [
    "FORECAST OVERVIEW",
    "DRIVER COMMENTARY",
    "KEY RISKS AND RECOMMENDATIONS",
    "DATA FLAGS",
]


def parse_sections(text):
    """Split the four-section commentary into {header: body} pairs."""
    sections = {}
    current = None
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped in _SECTION_HEADERS:
            if current is not None:
                sections[current] = "\n".join(lines).strip()
            current = stripped
            lines = []
        else:
            lines.append(line)
    if current is not None:
        sections[current] = "\n".join(lines).strip()
    return sections


def section_to_html(text):
    """Convert a commentary section's simple markdown to callout-safe HTML.

    Handles **bold**, bullet lines (- ), and paragraph breaks.
    """
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)

    lines = text.strip().split("\n")
    parts = []
    in_list = False
    para = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if para:
                parts.append("<p>{}</p>".format(" ".join(para)))
                para = []
            if in_list:
                parts.append("</ul>")
                in_list = False
            continue
        if stripped.startswith("- "):
            if para:
                parts.append("<p>{}</p>".format(" ".join(para)))
                para = []
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append("<li>{}</li>".format(stripped[2:]))
        else:
            if in_list:
                parts.append("</ul>")
                in_list = False
            para.append(stripped)

    if para:
        parts.append("<p>{}</p>".format(" ".join(para)))
    if in_list:
        parts.append("</ul>")

    return "\n".join(parts)
