# =============================================================================
# main.py — Project 2: Driver-Based Rolling Forecast Pipeline
# Pass 1: flat script, console output, understand every line
# =============================================================================

import pandas as pd
import anthropic
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

from config import (
    ANTHROPIC_API_KEY,
    MODEL,
    MAX_TOKENS,
    ACTUALS_FILE,
    DRIVER_FILE,
    OUTPUT_DIR,
    AUDIT_LOG,
    DEFAULT_ENTITY,
    FORECAST_HORIZON,
    VALID_DRIVER_TYPES,
    MAX_COGS_MARGIN,
    MAX_REVENUE,
)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

REQUIRED_ACTUALS_COLS = {"period", "line_item", "actual", "status"}
REQUIRED_DRIVER_COLS  = {"line_item", "driver_type", "driver_value"}


# =============================================================================
# STEP 1: Load and validate the actuals CSV
# =============================================================================
def load_actuals(filepath):
    """
    Load the year-to-date actuals CSV and return a validated DataFrame.

    Finance context: Actuals are historical facts — they are locked and
    must never be overwritten by forecast logic. Every row has a status
    of 'locked' confirming the period is closed.

    Validates: file exists, required columns present, no null values
    in key fields, all status values are 'locked'.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(
            "Actuals file not found: {}\n"
            "Expected: {}".format(filepath, filepath.resolve())
        )

    df = pd.read_csv(filepath, dtype={
        "period":    "str",
        "line_item": "str",
        "actual":    "float64",
        "status":    "str",
    })

    # Strip whitespace
    for col in ["period", "line_item", "status"]:
        if col in df.columns:
            df[col] = df[col].str.strip()

    # Validate required columns
    missing = REQUIRED_ACTUALS_COLS - set(df.columns)
    if missing:
        raise ValueError(
            "Actuals CSV missing columns: {}\n"
            "Found: {}".format(sorted(missing), sorted(df.columns))
        )

    # Validate no nulls in key fields
    for col in ["period", "line_item", "actual"]:
        if df[col].isna().any():
            raise ValueError(
                "Null values found in column '{}' — "
                "every row must have a value.".format(col)
            )

    # Validate all rows are locked
    unlocked = df[df["status"] != "locked"]
    if len(unlocked) > 0:
        raise ValueError(
            "{} rows have status != 'locked'.\n"
            "All actuals must be locked before running the forecast.\n"
            "Unlocked periods: {}".format(
                len(unlocked),
                unlocked["period"].unique().tolist()
            )
        )

    periods    = sorted(df["period"].unique())
    line_items = sorted(df["line_item"].unique())

    print("[OK] Actuals loaded")
    print("     Rows:       {}".format(len(df)))
    print("     Periods:    {} ({} to {})".format(
        len(periods), periods[0], periods[-1]))
    print("     Line items: {}".format(len(line_items)))
    print("     All rows locked: True")

    return df


# =============================================================================
# STEP 2: Load and validate the driver table CSV
# =============================================================================
def load_drivers(filepath):
    """
    Load the driver table and return a validated DataFrame.

    Finance context: The driver table is the control panel for the
    forecast. Each row defines how one line item grows in future periods.
    The driver_type tells Python which formula to apply.
    The driver_value is the assumption — the number a CFO would challenge.

    Validates: file exists, required columns present, all driver_types
    are recognised, no duplicate line items.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(
            "Driver file not found: {}".format(filepath)
        )

    df = pd.read_csv(filepath, dtype={
        "line_item":    "str",
        "driver_type":  "str",
        "driver_value": "float64",
    })

    for col in ["line_item", "driver_type"]:
        if col in df.columns:
            df[col] = df[col].str.strip()

    # Validate required columns
    missing = REQUIRED_DRIVER_COLS - set(df.columns)
    if missing:
        raise ValueError(
            "Driver CSV missing columns: {}".format(sorted(missing))
        )

    # Validate driver types are all recognised
    invalid_types = set(df["driver_type"]) - set(VALID_DRIVER_TYPES)
    if invalid_types:
        raise ValueError(
            "Unrecognised driver types: {}\n"
            "Valid types: {}".format(
                sorted(invalid_types), VALID_DRIVER_TYPES
            )
        )

    # Validate no duplicate line items
    dupes = df[df.duplicated("line_item", keep=False)]
    if len(dupes) > 0:
        raise ValueError(
            "Duplicate line items in driver table: {}\n"
            "Each line item must have exactly one driver.".format(
                dupes["line_item"].unique().tolist()
            )
        )

    print("[OK] Driver table loaded")
    print("     Rows:         {}".format(len(df)))
    print("     Driver types: {}".format(
        sorted(df["driver_type"].unique().tolist())))
    for _, row in df.iterrows():
        print("     {:20s} {:12s}  {}".format(
            row["line_item"], row["driver_type"],
            "{:,.3f}".format(row["driver_value"])
        ))

    return df


# =============================================================================
# STEP 3: Detect the actuals boundary and generate forecast periods
# =============================================================================
def detect_boundary(actuals_df):
    """
    Find the last locked period in actuals and generate forecast periods.

    Finance context: The boundary is the dividing line between fact and
    forecast. Everything on or before the boundary is actual. Everything
    after is calculated from drivers. This boundary moves forward each
    month as new actuals are locked.

    Returns:
        last_actual: string, e.g. '2026-06'
        forecast_periods: list of strings, e.g. ['2026-07', ..., '2026-12']
    """
    periods = sorted(actuals_df["period"].unique())
    last_actual = periods[-1]

    # Generate N forecast periods after the last actual
    year, month = map(int, last_actual.split("-"))
    forecast_periods = []
    for _ in range(FORECAST_HORIZON):
        month += 1
        if month > 12:
            month = 1
            year += 1
        forecast_periods.append("{:04d}-{:02d}".format(year, month))

    print("\n[OK] Boundary detected")
    print("     Last actual:      {}".format(last_actual))
    print("     Forecast periods: {} to {}".format(
        forecast_periods[0], forecast_periods[-1]))

    return last_actual, forecast_periods


# =============================================================================
# STEP 4: Calculate the rolling forecast
# =============================================================================
def calculate_forecast(actuals_df, drivers_df, last_actual, forecast_periods):
    """
    Apply driver logic to calculate forecast values period by period.

    This is the core engine of Project 2. For each forecast period and
    each line item, Python applies one of four formulas:

      growth_pct:   forecast = prior_period_value × (1 + rate)
      margin_pct:   forecast = Revenue_this_period × margin_rate
      fixed_growth: forecast = prior_period_value × (1 + rate)
      fixed:        forecast = driver_value (constant, ignores prior)

    Critical: COGS uses margin_pct which depends on the REVENUE forecast
    for the SAME period. Revenue must be calculated first each period.

    Args:
        actuals_df:       DataFrame of locked actuals
        drivers_df:       DataFrame of driver assumptions
        last_actual:      string — last locked period e.g. '2026-06'
        forecast_periods: list of period strings to forecast

    Returns:
        DataFrame with columns:
        period, line_item, value, type (actual/forecast)
    """
    # Build a lookup: {(period, line_item): value}
    # Starts with all actuals — forecast values are added as we go
    value_lookup = {}
    for _, row in actuals_df.iterrows():
        value_lookup[(row["period"], row["line_item"])] = row["actual"]

    # Build driver lookup: {line_item: {driver_type, driver_value}}
    driver_lookup = {}
    for _, row in drivers_df.iterrows():
        driver_lookup[row["line_item"]] = {
            "driver_type":  row["driver_type"],
            "driver_value": row["driver_value"],
        }

    # Line items in calculation order
    # Revenue MUST be first — COGS (margin_pct) depends on it
    line_items = actuals_df["line_item"].unique().tolist()
    if "Revenue" in line_items:
        line_items = ["Revenue"] + [li for li in line_items if li != "Revenue"]

    forecast_rows = []
    flags         = []

    for period in forecast_periods:
        # Prior period: for the first forecast period this is last_actual
        # For subsequent periods it is the previous forecast period
        idx = forecast_periods.index(period)
        prior_period = last_actual if idx == 0 else forecast_periods[idx - 1]

        revenue_this_period = None  # will be set when Revenue is calculated

        for line_item in line_items:
            if line_item not in driver_lookup:
                # No driver defined for this line item — flag it
                flags.append(
                    "MISSING_DRIVER: {} has no driver in driver_table.csv".format(
                        line_item
                    )
                )
                continue

            driver = driver_lookup[line_item]
            dtype  = driver["driver_type"]
            dvalue = driver["driver_value"]
            prior_value = value_lookup.get((prior_period, line_item))

            if prior_value is None:
                flags.append(
                    "MISSING_PRIOR: {} for period {} — "
                    "cannot calculate forecast".format(line_item, prior_period)
                )
                continue

            # ── Apply the driver formula ──────────────────────────────────
            if dtype == "growth_pct":
                forecast_value = prior_value * (1 + dvalue)

            elif dtype == "margin_pct":
                # Depends on Revenue for THIS period — must be calculated first
                if revenue_this_period is None:
                    flags.append(
                        "CALCULATION_ORDER: {} uses margin_pct but "
                        "Revenue not yet calculated for {}".format(
                            line_item, period
                        )
                    )
                    continue
                forecast_value = revenue_this_period * dvalue

            elif dtype == "fixed_growth":
                forecast_value = prior_value * (1 + dvalue)

            elif dtype == "fixed":
                forecast_value = dvalue

            else:
                flags.append(
                    "UNKNOWN_DRIVER_TYPE: {} for {}".format(dtype, line_item)
                )
                continue

            # ── Store Revenue for margin calculations ─────────────────────
            if line_item == "Revenue":
                revenue_this_period = forecast_value

            # ── Sanity checks ─────────────────────────────────────────────
            if forecast_value < 0:
                flags.append(
                    "NEGATIVE_VALUE: {} in {} = {:,.0f} — "
                    "review driver assumption".format(
                        line_item, period, forecast_value
                    )
                )

            if (line_item == "COGS"
                    and revenue_this_period
                    and (forecast_value / revenue_this_period) > MAX_COGS_MARGIN):
                flags.append(
                    "MARGIN_EXCEEDS_100PCT: COGS {:.1%} of Revenue in {}".format(
                        forecast_value / revenue_this_period, period
                    )
                )

            # ── Record the forecast row ───────────────────────────────────
            value_lookup[(period, line_item)] = forecast_value
            forecast_rows.append({
                "period":    period,
                "line_item": line_item,
                "value":     round(forecast_value, 2),
                "type":      "forecast",
            })

    # Build the full output DataFrame (actuals + forecast)
    actual_rows = []
    for _, row in actuals_df.iterrows():
        actual_rows.append({
            "period":    row["period"],
            "line_item": row["line_item"],
            "value":     row["actual"],
            "type":      "actual",
        })

    full_df = pd.DataFrame(actual_rows + forecast_rows)
    full_df = full_df.sort_values(["period", "line_item"]).reset_index(drop=True)

    # Summary
    actual_count   = len([r for r in actual_rows])
    forecast_count = len(forecast_rows)

    print("\n[OK] Forecast calculated")
    print("     Actual rows:   {}".format(actual_count))
    print("     Forecast rows: {}".format(forecast_count))
    print("     Flags raised:  {}".format(len(flags)))
    for flag in flags:
        print("     --> {}".format(flag))

    # Print forecast summary table
    print("\n     {:>7}  {:20s}  {:>14}  {:>14}  {:>8}".format(
        "Period", "Line Item", "Actual / Fcst", "Prior Period", "Change"
    ))
    print("     {}  {}  {}  {}  {}".format(
        "-"*7, "-"*20, "-"*14, "-"*14, "-"*8
    ))

    for period in sorted(actuals_df["period"].unique())[-2:] + forecast_periods:
        for line_item in line_items:
            val = value_lookup.get((period, period))  # placeholder
            val = value_lookup.get((period, line_item))
            if val is None:
                continue
            idx = list(actuals_df["period"].unique()) + forecast_periods
            period_idx = idx.index(period) if period in idx else -1
            prior_p = idx[period_idx - 1] if period_idx > 0 else None
            prior_v = value_lookup.get((prior_p, line_item)) if prior_p else None
            change  = ((val - prior_v) / prior_v) if prior_v else None
            dtype_label = "A" if period in actuals_df["period"].unique() else "F"
            print("     {:>7}{}  {:20s}  {:>14,.0f}  {:>14}  {:>8}".format(
                period,
                dtype_label,
                line_item,
                val,
                "{:>14,.0f}".format(prior_v) if prior_v else "           —",
                "{:>+8.1%}".format(change) if change else "       —",
            ))

    return full_df, flags


# =============================================================================
# STEP 5: Build prompts for Claude
# =============================================================================
def build_prompt(full_df, drivers_df, last_actual, forecast_periods, flags):
    """
    Build the system and user prompts for the Claude API call.

    Unlike Project 1 which asked Claude to narrate what happened,
    this prompt asks Claude to narrate what is EXPECTED to happen
    and WHY — based on the driver assumptions.

    The prompt contains four XML-tagged sections:
    1. <actuals_summary>     — recent 3 months of actuals for context
    2. <forecast_table>      — the Python-calculated 6-month forecast
    3. <driver_assumptions>  — the assumptions driving each line item
    4. <data_flags>          — any validation flags to mention

    Structure: context → data → query (Anthropic best practice)
    """

    # ── System prompt ─────────────────────────────────────────────────────────
    system_prompt = (
        "You are a senior FP&A analyst preparing a rolling forecast commentary "
        "for the CFO and Board of Valencia Operations.\n\n"
        "<role_context>\n"
        "You are reviewing a 6-month driver-based rolling forecast for H2 2026. "
        "The actuals for January through June 2026 are locked. "
        "The forecast for July through December 2026 has been calculated by the "
        "financial model using the driver assumptions provided.\n"
        "Your role is to narrate the FORWARD-LOOKING outlook, not to re-explain "
        "historical results. Focus on assumptions, risks, and recommendations.\n"
        "</role_context>\n\n"
        "<success_criteria>\n"
        "- Explain what each key driver assumption means in plain business terms\n"
        "- Identify which assumptions carry the most uncertainty or risk\n"
        "- Flag where the forecast implies a meaningful trend change vs recent actuals\n"
        "- Provide one specific recommendation for the CFO to challenge or validate\n"
        "- Tone: analytical, direct, CFO-ready — no hedging or filler phrases\n"
        "</success_criteria>\n\n"
        "<constraints>\n"
        "- NEVER invent numbers — only use figures from the data provided\n"
        "- Do not re-describe the actuals in detail — they are context, not the story\n"
        "- The story is: what does the next 6 months look like and why?\n"
        "- All amounts in EUR unless stated otherwise\n"
        "</constraints>\n\n"
        "<output_format>\n"
        "Produce output in exactly this structure:\n\n"
        "FORECAST OVERVIEW\n"
        "[3 sentences. H2 2026 total revenue forecast. "
        "Key cost trends. Overall implied P&L direction.]\n\n"
        "DRIVER COMMENTARY\n"
        "[One paragraph per line item. Format: "
        "Line Item: assumption in plain English. "
        "Implied trend vs recent actuals. Risk or confidence level.]\n\n"
        "KEY RISKS AND RECOMMENDATIONS\n"
        "[2-3 bullet points. The assumption the CFO should challenge most. "
        "The scenario that would most change the outlook. "
        "The one metric to watch closest in July.]\n\n"
        "DATA FLAGS\n"
        "[List each flag. If no flags, write: No flags raised.]\n"
        "</output_format>"
    )

    # ── Actuals summary (last 3 months for context) ───────────────────────────
    recent_periods = sorted(full_df[full_df["type"]=="actual"]["period"].unique())[-3:]
    actuals_lines  = []
    for period in recent_periods:
        period_data = full_df[
            (full_df["period"] == period) & (full_df["type"] == "actual")
        ]
        for _, row in period_data.iterrows():
            actuals_lines.append(
                "  {} | {:20s} | EUR {:>12,.0f}  [actual]".format(
                    row["period"], row["line_item"], row["value"]
                )
            )
    actuals_block = "\n".join(actuals_lines)

    # ── Forecast table ────────────────────────────────────────────────────────
    forecast_data = full_df[full_df["type"] == "forecast"]
    forecast_lines = []
    for period in forecast_periods:
        period_data = forecast_data[forecast_data["period"] == period]
        for _, row in period_data.sort_values("line_item").iterrows():
            forecast_lines.append(
                "  {} | {:20s} | EUR {:>12,.0f}  [forecast]".format(
                    row["period"], row["line_item"], row["value"]
                )
            )
    forecast_block = "\n".join(forecast_lines)

    # ── Driver assumptions ────────────────────────────────────────────────────
    driver_lines = []
    for _, row in drivers_df.iterrows():
        note = row.get("note", "") if "note" in row.index else ""
        driver_lines.append(
            "  {:20s} | {:12s} | {:>8} | {}".format(
                row["line_item"],
                row["driver_type"],
                "{:.1%}".format(row["driver_value"])
                    if row["driver_type"] in ["growth_pct","margin_pct","fixed_growth"]
                    else "EUR {:>8,.0f}".format(row["driver_value"]),
                note
            )
        )
    driver_block = "\n".join(driver_lines)

    # ── Flags block ───────────────────────────────────────────────────────────
    flags_block = (
        "\n".join("  - {}".format(f) for f in flags)
        if flags else "  No flags raised."
    )

    # ── Assemble user prompt ──────────────────────────────────────────────────
    user_prompt = (
        "FORECAST CONTEXT\n"
        "Entity:          {entity}\n"
        "Last actual:     {last_actual}\n"
        "Forecast period: {fcst_start} to {fcst_end}\n"
        "Horizon:         {horizon} months\n\n"
        "<actuals_summary>\n"
        "{actuals}\n"
        "</actuals_summary>\n\n"
        "<forecast_table>\n"
        "{forecast}\n"
        "</forecast_table>\n\n"
        "<driver_assumptions>\n"
        "{drivers}\n"
        "</driver_assumptions>\n\n"
        "<data_flags>\n"
        "{flags}\n"
        "</data_flags>\n\n"
        "Using the forecast table and driver assumptions above, produce the "
        "rolling forecast commentary in the exact output format specified."
    ).format(
        entity     = DEFAULT_ENTITY,
        last_actual= last_actual,
        fcst_start = forecast_periods[0],
        fcst_end   = forecast_periods[-1],
        horizon    = FORECAST_HORIZON,
        actuals    = actuals_block,
        forecast   = forecast_block,
        drivers    = driver_block,
        flags      = flags_block,
    )

    print("\n[OK] Prompts built")
    print("     Actuals context: {} rows (last 3 months)".format(
        len(actuals_lines)))
    print("     Forecast rows:   {}".format(len(forecast_lines)))
    print("     Driver rows:     {}".format(len(driver_lines)))
    print("     Flags:           {}".format(len(flags)))

    return system_prompt, user_prompt


# =============================================================================
# STEP 6: Call Claude
# =============================================================================
def call_claude(system_prompt, user_prompt):
    """
    Send prompts to Claude and return commentary.
    Same pattern as Project 1 — error handling unchanged.
    """
    print("\n[..] Calling Claude API ({})...".format(MODEL))

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
    except anthropic.AuthenticationError:
        raise RuntimeError(
            "Authentication failed. Check ANTHROPIC_API_KEY in .env."
        )
    except anthropic.RateLimitError:
        raise RuntimeError(
            "Rate limit reached. Wait 60 seconds and try again."
        )
    except anthropic.APIStatusError as e:
        raise RuntimeError(
            "API error {}: {}".format(e.status_code, e.message)
        )
    except anthropic.APIConnectionError:
        raise RuntimeError(
            "Cannot connect to Anthropic API. Check internet connection."
        )

    if not response.content:
        raise RuntimeError("Claude returned an empty response.")

    response_text = response.content[0].text
    input_tokens  = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    stop_reason   = response.stop_reason

    if stop_reason == "max_tokens":
        print("[WARN] Response truncated. Consider increasing MAX_TOKENS.")

    if output_tokens < 200 and stop_reason != "max_tokens":
        print("[WARN] Unusually low output ({} tokens). Review output.".format(
            output_tokens))

    approx_cost = (input_tokens * 0.000003) + (output_tokens * 0.000015)

    print("[OK] Claude responded")
    print("     Stop reason:   {}".format(stop_reason))
    print("     Input tokens:  {:,}".format(input_tokens))
    print("     Output tokens: {:,}".format(output_tokens))
    print("     Approx cost:   EUR {:.4f}".format(approx_cost))
    print("\n{}".format("=" * 60))
    print("ROLLING FORECAST COMMENTARY — {}".format(DEFAULT_ENTITY))
    print("{}".format("=" * 60))
    print(response_text.encode("utf-8", errors="replace").decode("utf-8"))
    print("{}".format("=" * 60))

    return response_text, input_tokens, output_tokens, stop_reason


# =============================================================================
# STEP 7: Write output and audit log
# =============================================================================
def write_output(commentary, full_df, flags, tok_in, tok_out,
                 stop_reason, last_actual, forecast_periods):
    """
    Write commentary to a timestamped text file and append audit record.
    Adds forecast-specific fields: last_actual, forecast_start, forecast_end.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    now     = datetime.now(timezone.utc)
    ts_file = now.strftime("%Y-%m-%d_%H-%M-%S")
    ts_log  = now.isoformat()

    output_filename = "forecast_commentary_{}.txt".format(ts_file)
    output_path     = OUTPUT_DIR / output_filename

    header = (
        "ROLLING FORECAST COMMENTARY - GENERATED OUTPUT\n"
        "{sep}\n"
        "Generated:       {ts}\n"
        "Entity:          {entity}\n"
        "Last actual:     {last_actual}\n"
        "Forecast period: {fcst_start} to {fcst_end}\n"
        "Horizon:         {horizon} months\n"
        "Model:           {model}\n"
        "Tokens:          {tin:,} in / {tout:,} out\n"
        "Flags:           {nflags} raised\n"
        "{sep}\n\n"
    ).format(
        sep          = "=" * 60,
        ts           = ts_log,
        entity       = DEFAULT_ENTITY,
        last_actual  = last_actual,
        fcst_start   = forecast_periods[0],
        fcst_end     = forecast_periods[-1],
        horizon      = FORECAST_HORIZON,
        model        = MODEL,
        tin          = tok_in,
        tout         = tok_out,
        nflags       = len(flags),
    )

    output_path.write_text(header + commentary, encoding="utf-8")

    # SHA256 hash of actuals file
    with open(ACTUALS_FILE, "rb") as f:
        actuals_hash = "sha256:" + hashlib.sha256(f.read()).hexdigest()
    with open(DRIVER_FILE, "rb") as f:
        driver_hash = "sha256:" + hashlib.sha256(f.read()).hexdigest()

    requires_review = (
        len(flags) > 0
        or stop_reason == "max_tokens"
        or (tok_out < 200 and stop_reason != "max_tokens")
    )

    audit_record = {
        "run_id":           ts_log,
        "project":          "rolling-forecast-pipeline",
        "entity":           DEFAULT_ENTITY,
        "last_actual":      last_actual,
        "forecast_start":   forecast_periods[0],
        "forecast_end":     forecast_periods[-1],
        "horizon_months":   FORECAST_HORIZON,
        "actuals_rows":     len(full_df[full_df["type"] == "actual"]),
        "forecast_rows":    len(full_df[full_df["type"] == "forecast"]),
        "actuals_hash":     actuals_hash,
        "driver_hash":      driver_hash,
        "output_file":      str(output_path),
        "pdf_file":         None,
        "model":            MODEL,
        "input_tokens":     tok_in,
        "output_tokens":    tok_out,
        "stop_reason":      stop_reason,
        "flags_raised":     flags,
        "human_reviewed":   False,
        "requires_review":  requires_review,
    }

    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(audit_record) + "\n")

    print("\n[OK] Output written")
    print("     Commentary: {}".format(output_path))
    print("     Audit log:  {}".format(AUDIT_LOG))
    print("     Actuals hash: {}...".format(actuals_hash[:30]))
    print("     Driver hash:  {}...".format(driver_hash[:30]))
    print("     Requires human review: {}".format(requires_review))
    if requires_review and flags:
        print("     Reason: {} flag(s) raised".format(len(flags)))

    return output_path, audit_record


# =============================================================================
# MAIN — runs the full pipeline
# =============================================================================
if __name__ == "__main__":

    # Step 1: Load actuals
    actuals_df = load_actuals(ACTUALS_FILE)

    # Step 2: Load drivers
    drivers_df = load_drivers(DRIVER_FILE)

    # Step 3: Detect boundary
    last_actual, forecast_periods = detect_boundary(actuals_df)

    # Step 4: Calculate forecast
    full_df, flags = calculate_forecast(
        actuals_df, drivers_df, last_actual, forecast_periods
    )

    # Step 5: Build prompts
    system_prompt, user_prompt = build_prompt(
        full_df, drivers_df, last_actual, forecast_periods, flags
    )

    # Step 6: Call Claude
    commentary, tok_in, tok_out, stop_reason = call_claude(
        system_prompt, user_prompt
    )

    # Step 7: Write output
    output_path, audit = write_output(
        commentary, full_df, flags,
        tok_in, tok_out, stop_reason,
        last_actual, forecast_periods
    )

    print("\n[DONE] Pipeline complete.")
    print("       Output: {}".format(output_path))

    # Human review check
    if audit.get("requires_review"):
        print("\n" + "!" * 60)
        print("  HUMAN REVIEW REQUIRED")
        print("!" * 60)
        for flag in audit.get("flags_raised", []):
            print("  -> {}".format(flag))
        print("!" * 60)
    else:
        print("\n[OK] No human review required.")
