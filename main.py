# =============================================================================
# main.py — Project 2: Driver-Based Rolling Forecast Pipeline
# Pass 2: four-layer architecture (all steps extracted)
# =============================================================================

from dotenv import load_dotenv

load_dotenv()

from src.step1_data_loader import (
    load_actuals, load_drivers, detect_boundary,
    load_operational_actuals, load_headcount_schedule, load_customer_targets,
)
from src.step2_forecast_engine import calculate_forecast, build_pnl
from src.step3_ai_engine       import build_prompt, call_claude
from src.step4_output_writer   import write_output, write_pdf, export_pnl_csv
from config import (
    ACTUALS_FILE,
    DRIVER_FILE,
    OPERATIONAL_FILE,
    HEADCOUNT_FILE,
    CUSTOMER_FILE,
)


# =============================================================================
# MAIN — runs the full pipeline
# =============================================================================
if __name__ == "__main__":

    # Step 1: Load all inputs
    actuals_df     = load_actuals(ACTUALS_FILE)
    drivers_df     = load_drivers(DRIVER_FILE)
    operational_df = load_operational_actuals(OPERATIONAL_FILE)
    headcount_df   = load_headcount_schedule(HEADCOUNT_FILE)
    customer_df    = load_customer_targets(CUSTOMER_FILE)

    # Step 2: Detect boundary
    last_actual, forecast_periods = detect_boundary(actuals_df)

    # Seasonality is derived from the most recent complete calendar year.
    # With actuals through 2026-06, that is the full 2025 calendar year.
    seasonal_year = int(last_actual.split("-")[0]) - 1

    # Step 3: Calculate forecast (Python does all the maths)
    full_df, driver_detail, flags = calculate_forecast(
        actuals_df, drivers_df, operational_df,
        headcount_df, customer_df,
        last_actual, forecast_periods, seasonal_year
    )

    # Step 4: Roll up into a simplified P&L
    pnl_df = build_pnl(full_df, forecast_periods)

    # Step 5: Build prompts
    system_prompt, user_prompt = build_prompt(
        full_df, pnl_df, driver_detail, drivers_df,
        last_actual, forecast_periods, flags
    )

    # Step 6: Call Claude
    commentary, tok_in, tok_out, stop_reason = call_claude(
        system_prompt, user_prompt
    )

    # Step 7: Write output
    txt_path, audit = write_output(
        commentary, full_df, flags,
        tok_in, tok_out, stop_reason,
        last_actual, forecast_periods, seasonal_year
    )

    # Step 8: Write PDF
    pdf_path = write_pdf(
        commentary, full_df, pnl_df, drivers_df, flags,
        tok_in, tok_out, last_actual, forecast_periods
    )

    # Step 9: Export full P&L to CSV
    csv_path = export_pnl_csv(pnl_df, full_df, forecast_periods)

    print("\n[DONE] Pipeline complete.")
    print("       Text: {}".format(txt_path))
    print("       PDF:  {}".format(pdf_path))

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
