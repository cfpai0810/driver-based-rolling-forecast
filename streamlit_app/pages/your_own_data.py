# =============================================================================
# pages/your_own_data.py -- instructions for running on your own data
# =============================================================================
# Reads docs/bring_your_own_data.md at runtime and renders it. The markdown
# file is the single source of truth; this page just displays it.
# =============================================================================

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit_app.lib.theme import inject_css

st.markdown(inject_css(), unsafe_allow_html=True)

md_path = ROOT / "docs" / "bring_your_own_data.md"
body = md_path.read_text(encoding="utf-8")

lines = body.split("\n")
if lines and lines[0].startswith("# "):
    title = lines[0][2:].strip()
    body = "\n".join(lines[1:])
else:
    title = "Your own data"

st.markdown("### {}".format(title))

sections = body.split("\n## ")
for i, section in enumerate(sections):
    if i == 0:
        st.markdown(section.strip())
    else:
        st.markdown("---")
        content = "## " + section
        content = content.replace("\n### ", "\n#### ")
        st.markdown(content)

st.divider()
st.caption("Sample data only. All figures are illustrative.")
