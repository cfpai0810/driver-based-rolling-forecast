# =============================================================================
# pages/how_its_built.py: trust story then technical depth
# =============================================================================
# Two audiences on one page. Part 1 is for a finance leader: why a forecast
# tool with AI commentary can be trusted (the governance model, the
# deterministic core, the audit trail). Part 2 is for an engineer or technical
# evaluator: the pipeline, the module boundaries, the AI boundary as a design
# choice, and the test coverage.
# =============================================================================

import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit_app.lib.theme import inject_css
from streamlit_app.lib.governance_flow import governance_flow_svg
from streamlit_app.lib.governance_lifecycle import governance_lifecycle_svg
from streamlit_app.lib.pipeline_flow import pipeline_flow_svg

st.markdown(inject_css(), unsafe_allow_html=True)

st.markdown("### How it's built")
st.write(
    "This tool was built on one principle: an AI system that touches financial "
    "numbers has to earn trust before it earns time. The sections below explain "
    "how that principle shapes the design, first for a finance reader and then "
    "in technical detail.")

# -- Part 1: the trust story (finance reader) ---------------------------------
st.markdown("---")
st.markdown("#### Why you can trust the numbers")

st.write(
    "The tool never lets the language model do arithmetic. That is the whole "
    "idea. A large language model is good at describing a result in plain "
    "words, but it is not a calculator and it is not asked to be one. Every "
    "figure you see is computed by deterministic Python code, the same way a "
    "spreadsheet would, and the same inputs always produce the same output.")

st.markdown("**The work happens in separated layers, and you open and close "
            "every one.**")
components.html(governance_flow_svg(), height=220, scrolling=False)
st.write(
    "You set each driver's method and value; Python computes the entire P&L "
    "from those drivers with the model absent from the calculation; the model "
    "then narrates the result it was handed; deterministic rules flag anything "
    "that needs scrutiny; and you review the output. If you change a driver "
    "after commentary was written, the tool clears the stale commentary and "
    "requires a fresh run.")

st.markdown("**Every run leaves a record.**")
st.write(
    "Each forecast run, whether it included commentary or not, is recorded in "
    "the session audit trail with a fingerprint of the exact P&L, the "
    "effective drivers, dual hashes of the input files, token counts, cost, "
    "and whether review was recommended. The point is that a forecast is "
    "reproducible and reviewable after the fact, which is what a finance "
    "function needs before it will rely on any tool.")

st.info(
    "In one line: you set the drivers, Python calculates every figure, the "
    "model writes the commentary, and you approve the result. The intelligence "
    "is at the edges, and the numbers in the middle are deterministic and "
    "checkable.")

st.markdown("#### The governance lifecycle")
components.html(governance_lifecycle_svg(), height=310, scrolling=False)
st.write(
    "In a production deployment, review is the start of the record, not "
    "the end. Once a reviewer approves the commentary, the approved version "
    "becomes the immutable record: it is what everyone reads afterwards, "
    "and it cannot be edited. A later change is issued as a new, "
    "separately approved version, and the original still stands unchanged. "
    "This live demo stops at flagging for review; it does not store or lock "
    "anything, so no data is retained. The lifecycle diagram above shows the "
    "full model this design is built towards.")

# -- Part 2: the technical detail (engineer / evaluator) ----------------------
st.markdown("---")
st.markdown("#### The technical detail")

st.write(
    "The system is a small, layered pipeline. Each stage has one responsibility, "
    "and the boundary between the AI stage and the deterministic stages is "
    "deliberate and strict.")

st.markdown("**The pipeline.**")
components.html(pipeline_flow_svg(), height=260, scrolling=False)
st.write(
    "Each stage has one job. The data layer loads five CSV files and finds the "
    "boundary between actuals and the forecast horizon. The forecast engine "
    "applies six driver types period by period and rolls them into a profit "
    "and loss. The validator checks bounds and flags anomalies. The commentary "
    "stage calls the model to narrate the already-final figures. The output "
    "stage writes the PDF, CSV, and audit record.")

st.markdown("**The AI boundary is the important design choice.**")
st.write(
    "The language model appears in exactly one stage: the commentary, which is "
    "given already-computed figures and asked only to describe them. Everything "
    "numeric, the forecast, the validation, the P&L roll-up, is deterministic "
    "Python. This is what makes the output reproducible and testable. It also "
    "means the model's known weakness, arithmetic, is never on the critical "
    "path.")

st.markdown("**The stale-clear fingerprint.**")
st.write(
    "The forecast page computes a SHA-256 fingerprint of the P&L's numeric "
    "values. When the fingerprint changes (because a driver was adjusted), "
    "any existing commentary is cleared automatically. This prevents stale "
    "commentary from describing a forecast that no longer exists, and forces "
    "a fresh run before the user can download a report with commentary.")

st.markdown("**Safety properties that are enforced, not hoped for.**")
st.write(
    "The base forecast is cached and never mutated. Driver overrides are "
    "applied on a copy, so resetting to defaults is instant and lossless. "
    "The commentary fingerprint is checked on every render. Downloads build "
    "the PDF and CSV to memory from the same shared builders the CLI uses, "
    "so web and CLI outputs are identical. Each of these properties is covered "
    "by a test.")

st.markdown("**Tested to a level a finance tool should be.**")
st.write(
    "The suite covers the forecast engine, the driver controls mapping, "
    "the commentary fingerprint and section parsing, the shared output "
    "builders (PDF with and without commentary, CSV content, data hashes), "
    "the requires-review logic across five branches, and the audit record "
    "shape. The web layer reuses the same tested pipeline unchanged; the "
    "pages orchestrate and render, they never recompute.")

st.markdown("**Built for a public, keyless demo.**")
st.write(
    "Everything here runs on a synthetic sample entity, so there is no "
    "confidential data anywhere in the app or its history. The forecast page "
    "includes a worked example that needs no API key: the base forecast shows "
    "captured commentary from a real run, so the reasoning and the output are "
    "visible even without running a live analysis.")

st.markdown("---")
st.caption(
    "The sample data is synthetic and the figures are illustrative. The "
    "architecture, the governance model, and the test coverage are real.")
