# =============================================================================
# lib/audit.py -- session-only audit trail for forecast runs
# =============================================================================
# Follows the same pattern as Projects 3 and 4: session state, no disk writes,
# cleared when the browser tab closes. The build_audit_record function is pure
# (no Streamlit dependency) so it can be tested headless.
# =============================================================================

from datetime import datetime, timezone

import streamlit as st

from streamlit_app.lib.cost import estimate_cost

AUDIT_KEY = "forecast_audit"


def build_audit_record(eff_drivers_df, fingerprint, actuals_hash, driver_hash,
                       flags, has_commentary=False, tok_in=0, tok_out=0,
                       stop_reason=None, overrides=None):
    """Build an audit record dict. Pure function, no Streamlit dependency.

    Parameters
    ----------
    eff_drivers_df : DataFrame
        The effective driver table (base or with overrides applied).
    fingerprint : str
        The 16-char forecast fingerprint from commentary.forecast_fingerprint.
    actuals_hash, driver_hash : str
        SHA-256 hashes of the input files.
    flags : list[str]
        Validation flags from the forecast engine.
    has_commentary : bool
        Whether AI commentary was generated for this run.
    tok_in, tok_out : int
        Token counts (0 when no commentary).
    stop_reason : str or None
        Claude stop reason (None when no commentary).
    overrides : dict or None
        The driver_overrides dict, if any adjustments were applied.
    """
    from config import MODEL
    from src.step4_output_writer import check_requires_review

    drivers_summary = []
    for _, row in eff_drivers_df.iterrows():
        drivers_summary.append({
            "line": row["line_item"],
            "method": row["driver_type"],
            "value": float(row["driver_value"]),
        })

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fingerprint": fingerprint,
        "actuals_hash": actuals_hash,
        "driver_hash": driver_hash,
        "effective_drivers": drivers_summary,
        "overrides_applied": overrides is not None,
        "flags": list(flags),
        "has_commentary": has_commentary,
        "model": MODEL if has_commentary else None,
        "tokens_in": tok_in,
        "tokens_out": tok_out,
        "cost": estimate_cost(tok_in, tok_out) if has_commentary else None,
        "requires_review": check_requires_review(
            flags, stop_reason, tok_out, has_commentary,
        ),
    }
    return record


def record_run(**kwargs):
    """Build an audit record and store it in session state (newest first)."""
    if AUDIT_KEY not in st.session_state:
        st.session_state[AUDIT_KEY] = []
    rec = build_audit_record(**kwargs)
    st.session_state[AUDIT_KEY].insert(0, rec)
    return rec


def get_runs():
    """Return all audit records (newest first)."""
    return st.session_state.get(AUDIT_KEY, [])
