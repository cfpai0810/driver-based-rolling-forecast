# =============================================================================
# lib/driver_controls.py -- pure logic for the driver-adjust surface
# =============================================================================
# Testable without Streamlit. The page reads widget state and calls these
# functions to build the engine's driver_overrides dict.
# =============================================================================

from streamlit_app.lib.driver_menu import METHOD_VALUE_SHAPE


def to_display(method, engine_value):
    """Convert an engine value to its display form.

    Percentage methods are stored as decimals (0.12) but displayed as
    percentages (12.0). Currency and schedule values pass through.
    """
    if engine_value is None:
        return 0.0
    shape = METHOD_VALUE_SHAPE[method]
    if shape == "pct":
        return engine_value * 100.0
    return float(engine_value)


def to_engine(method, display_value):
    """Convert a display value back to the engine's decimal form."""
    shape = METHOD_VALUE_SHAPE[method]
    if shape == "pct":
        return display_value / 100.0
    return display_value


def build_overrides(method_values):
    """Build driver_overrides from {line: (method, display_value)}.

    Schedule-driven lines are excluded (they use CSV data directly).
    Returns a dict suitable for calculate_forecast(driver_overrides=...),
    or None if every line is schedule-driven.
    """
    overrides = {}
    for line, (method, display_val) in method_values.items():
        if METHOD_VALUE_SHAPE[method] == "schedule":
            continue
        overrides[line] = {"method": method, "value": to_engine(method, display_val)}
    return overrides if overrides else None
