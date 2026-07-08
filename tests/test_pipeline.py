# =============================================================================
# tests/test_pipeline.py — Project 2: Driver-Based Rolling Forecast Pipeline
# =============================================================================
# Phase 5: VALIDATE
#
# Run from the project root with (venv) active:
#   pytest tests/test_pipeline.py -v
#
# Nine test classes covering the full surface area of the pipeline:
#   1. Data loading            — all five input files load and validate
#   2. Seasonal derivation      — indices sum to 12, summer dip, Q4 peak
#   3. seasonal_yoy forecast     — trailing 12m, annual target, monthly spread
#   4. headcount_driven forecast — starting headcount, hires, attrition
#   5. cac_driven forecast       — new customers x CAC + fixed campaign
#   6. Simple drivers            — margin_pct, growth_pct, fixed
#   7. P&L roll-up               — Gross Profit, EBIT, margins, weakest month
#   8. Validation flags          — clean data, and the flag conditions
#   9. Output writing            — dual hashes, audit record, review logic
#
# No real API calls are made. The Claude call is mocked so the suite runs
# in a couple of seconds and costs nothing.
# =============================================================================

import json
import pytest
import pandas as pd

from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.step1_data_loader import (
    load_actuals, load_drivers, detect_boundary,
    load_operational_actuals, load_headcount_schedule, load_customer_targets,
)
from src.step2_forecast_engine import (
    derive_seasonal_indices, calculate_forecast, build_pnl,
)
from src.step4_output_writer import write_output
from config import (
    ACTUALS_FILE, DRIVER_FILE, OPERATIONAL_FILE, HEADCOUNT_FILE, CUSTOMER_FILE,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def actuals_df():
    return load_actuals(ACTUALS_FILE)


@pytest.fixture
def drivers_df():
    return load_drivers(DRIVER_FILE)


@pytest.fixture
def operational_df():
    return load_operational_actuals(OPERATIONAL_FILE)


@pytest.fixture
def headcount_df():
    return load_headcount_schedule(HEADCOUNT_FILE)


@pytest.fixture
def customer_df():
    return load_customer_targets(CUSTOMER_FILE)


@pytest.fixture
def boundary(actuals_df):
    return detect_boundary(actuals_df)


@pytest.fixture
def forecast_periods(boundary):
    return boundary[1]


@pytest.fixture
def last_actual(boundary):
    return boundary[0]


@pytest.fixture
def seasonal_year(last_actual):
    return int(last_actual.split("-")[0]) - 1


@pytest.fixture
def forecast_result(actuals_df, drivers_df, operational_df, headcount_df,
                    customer_df, last_actual, forecast_periods, seasonal_year):
    """Run the full forecast once and reuse across tests."""
    return calculate_forecast(
        actuals_df, drivers_df, operational_df, headcount_df, customer_df,
        last_actual, forecast_periods, seasonal_year
    )


@pytest.fixture
def full_df(forecast_result):
    return forecast_result[0]


@pytest.fixture
def driver_detail(forecast_result):
    return forecast_result[1]


@pytest.fixture
def flags(forecast_result):
    return forecast_result[2]


@pytest.fixture
def pnl_df(full_df, forecast_periods):
    return build_pnl(full_df, forecast_periods)


@pytest.fixture
def tmp_dirs(tmp_path):
    out_dir = tmp_path / "output"
    audit   = out_dir / "audit_log.jsonl"
    out_dir.mkdir()
    with patch("src.step4_output_writer.OUTPUT_DIR", out_dir), \
         patch("src.step4_output_writer.AUDIT_LOG",  audit):
        yield out_dir, audit


# =============================================================================
# CLASS 1: Data loading
# =============================================================================

class TestDataLoading:

    def test_actuals_row_count(self, actuals_df):
        assert len(actuals_df) == 108   # 18 months x 6 line items

    def test_actuals_all_locked(self, actuals_df):
        assert (actuals_df["status"] == "locked").all()

    def test_actuals_six_line_items(self, actuals_df):
        assert actuals_df["line_item"].nunique() == 6

    def test_actuals_dtypes(self, actuals_df):
        assert str(actuals_df["actual"].dtype) == "float64"

    def test_drivers_six_rows(self, drivers_df):
        assert len(drivers_df) == 6

    def test_drivers_have_new_types(self, drivers_df):
        types = set(drivers_df["driver_type"])
        assert "seasonal_yoy"     in types
        assert "headcount_driven" in types
        assert "cac_driven"       in types

    def test_operational_has_headcount(self, operational_df):
        assert "headcount" in operational_df["metric"].values

    def test_operational_has_new_customers(self, operational_df):
        assert "new_customers" in operational_df["metric"].values

    def test_headcount_schedule_periods(self, headcount_df):
        assert len(headcount_df) == 6

    def test_customer_targets_periods(self, customer_df):
        assert len(customer_df) == 6

    def test_boundary_last_actual(self, last_actual):
        assert last_actual == "2026-06"

    def test_boundary_six_forecast_periods(self, forecast_periods):
        assert len(forecast_periods) == 6

    def test_boundary_first_and_last(self, forecast_periods):
        assert forecast_periods[0]  == "2026-07"
        assert forecast_periods[-1] == "2026-12"


# =============================================================================
# CLASS 2: Seasonal derivation — the automation showcase
# =============================================================================

class TestSeasonalDerivation:

    def test_indices_sum_to_twelve(self, actuals_df):
        idx = derive_seasonal_indices(actuals_df, "Revenue", 2025)
        assert abs(sum(idx.values()) - 12.0) < 0.001

    def test_indices_mean_to_one(self, actuals_df):
        idx = derive_seasonal_indices(actuals_df, "Revenue", 2025)
        assert abs(sum(idx.values()) / 12 - 1.0) < 0.001

    def test_summer_months_below_average(self, actuals_df):
        idx = derive_seasonal_indices(actuals_df, "Revenue", 2025)
        assert idx["07"] < 1.0   # July dip
        assert idx["08"] < 1.0   # August trough

    def test_q4_months_above_average(self, actuals_df):
        idx = derive_seasonal_indices(actuals_df, "Revenue", 2025)
        assert idx["11"] > 1.0   # November
        assert idx["12"] > 1.0   # December

    def test_december_is_peak(self, actuals_df):
        idx = derive_seasonal_indices(actuals_df, "Revenue", 2025)
        assert idx["12"] == max(idx.values())

    def test_raises_on_incomplete_year(self, actuals_df):
        # 2024 has no data at all — should raise
        with pytest.raises(ValueError):
            derive_seasonal_indices(actuals_df, "Revenue", 2024)


# =============================================================================
# CLASS 3: seasonal_yoy revenue forecast
# =============================================================================

class TestSeasonalYoYForecast:

    def test_trailing_twelve_months(self, driver_detail):
        # Jul 2025 to Jun 2026 revenue = 14,475,000
        assert abs(driver_detail["Revenue"]["trailing_12m"] - 14475000) < 1

    def test_annual_target(self, driver_detail):
        d = driver_detail["Revenue"]
        assert abs(d["annual_target"] - d["trailing_12m"] * 1.12) < 1

    def test_july_below_june_actual(self, full_df):
        # Summer dip: July forecast lower than June actual (1,290,000)
        jul = full_df[(full_df["period"]=="2026-07") &
                      (full_df["line_item"]=="Revenue")]["value"].iloc[0]
        assert jul < 1290000

    def test_december_is_peak_forecast(self, full_df):
        fc = full_df[(full_df["type"]=="forecast") & (full_df["line_item"]=="Revenue")]
        dec = fc[fc["period"]=="2026-12"]["value"].iloc[0]
        assert dec == fc["value"].max()

    def test_august_is_trough_forecast(self, full_df):
        fc = full_df[(full_df["type"]=="forecast") & (full_df["line_item"]=="Revenue")]
        aug = fc[fc["period"]=="2026-08"]["value"].iloc[0]
        assert aug == fc["value"].min()


# =============================================================================
# CLASS 4: headcount_driven personnel forecast
# =============================================================================

class TestHeadcountDriven:

    def test_starting_headcount_from_actuals(self, driver_detail):
        # Read directly from operational actuals — 42 heads in Jun 2026
        assert driver_detail["Personnel Cost"]["start_headcount"] == 42

    def test_july_headcount_rolls(self, driver_detail):
        # 42 start + 2 hires - 1 attrition = 43
        assert driver_detail["Personnel Cost"]["schedule"]["2026-07"]["end"] == 43

    def test_september_headcount(self, driver_detail):
        # 43 + 3 - 1 = 45
        assert driver_detail["Personnel Cost"]["schedule"]["2026-09"]["end"] == 45

    def test_attrition_rounds(self, driver_detail):
        # 42 x 0.015 = 0.63 rounds to 1
        assert driver_detail["Personnel Cost"]["schedule"]["2026-07"]["attrition"] == 1

    def test_july_cost_is_avg_headcount_times_rate(self, full_df):
        # avg of 42 and 43 heads x (78000/12) monthly cost per head
        jul = full_df[(full_df["period"]=="2026-07") &
                      (full_df["line_item"]=="Personnel Cost")]["value"].iloc[0]
        expected = ((42 + 43) / 2) * (78000 / 12)
        assert abs(jul - expected) < 1


# =============================================================================
# CLASS 5: cac_driven marketing forecast
# =============================================================================

class TestCACDriven:

    def test_july_marketing(self, full_df):
        # 45 customers x 1200 CAC + 25000 fixed
        jul = full_df[(full_df["period"]=="2026-07") &
                      (full_df["line_item"]=="Marketing Spend")]["value"].iloc[0]
        assert jul == 45 * 1200 + 25000

    def test_november_marketing(self, full_df):
        # 70 customers x 1200 + 25000
        nov = full_df[(full_df["period"]=="2026-11") &
                      (full_df["line_item"]=="Marketing Spend")]["value"].iloc[0]
        assert nov == 70 * 1200 + 25000

    def test_each_period_uses_own_target(self, full_df):
        # July and August differ because targets differ
        fc = full_df[(full_df["type"]=="forecast") &
                     (full_df["line_item"]=="Marketing Spend")]
        jul = fc[fc["period"]=="2026-07"]["value"].iloc[0]
        aug = fc[fc["period"]=="2026-08"]["value"].iloc[0]
        assert jul != aug


# =============================================================================
# CLASS 6: simple driver types
# =============================================================================

class TestSimpleDrivers:

    def _val(self, full_df, line_item, period):
        return full_df[(full_df["period"]==period) &
                       (full_df["line_item"]==line_item)]["value"].iloc[0]

    def test_cogs_is_margin_of_revenue(self, full_df):
        cogs = self._val(full_df, "COGS", "2026-07")
        rev  = self._val(full_df, "Revenue", "2026-07")
        assert abs(cogs - rev * 0.418) < 1

    def test_it_infrastructure_fixed(self, full_df):
        assert self._val(full_df, "IT Infrastructure", "2026-07") == 45000
        assert self._val(full_df, "IT Infrastructure", "2026-12") == 45000

    def test_rd_compounds_monthly(self, full_df):
        jul = self._val(full_df, "R&D Expense", "2026-07")
        aug = self._val(full_df, "R&D Expense", "2026-08")
        assert abs(aug - jul * 1.06) < 1


# =============================================================================
# CLASS 7: P&L roll-up
# =============================================================================

class TestPnLRollup:

    def _total(self, pnl_df, line):
        return float(pnl_df[pnl_df["line"] == line]["total"].iloc[0])

    def test_h2_revenue(self, pnl_df):
        assert abs(self._total(pnl_df, "Revenue") - 8490872) < 100

    def test_h2_gross_profit(self, pnl_df):
        assert abs(self._total(pnl_df, "Gross Profit") - 4941688) < 100

    def test_h2_ebit(self, pnl_df):
        assert abs(self._total(pnl_df, "Operating Profit (EBIT)") - 542191) < 100

    def test_gross_profit_equals_revenue_minus_cogs(self, pnl_df):
        rev  = self._total(pnl_df, "Revenue")
        cogs = self._total(pnl_df, "COGS")
        gp   = self._total(pnl_df, "Gross Profit")
        assert abs(gp - (rev - cogs)) < 1

    def test_ebit_equals_gross_minus_opex(self, pnl_df):
        gp   = self._total(pnl_df, "Gross Profit")
        opex = self._total(pnl_df, "Total OpEx")
        ebit = self._total(pnl_df, "Operating Profit (EBIT)")
        assert abs(ebit - (gp - opex)) < 1

    def test_august_is_weakest_ebit_month(self, pnl_df, forecast_periods):
        ebit_row = pnl_df[pnl_df["line"] == "Operating Profit (EBIT)"].iloc[0]
        monthly = {p: ebit_row[p] for p in forecast_periods}
        assert min(monthly, key=monthly.get) == "2026-08"

    def test_pnl_has_all_lines(self, pnl_df):
        lines = set(pnl_df["line"])
        assert "Revenue"                 in lines
        assert "Gross Profit"            in lines
        assert "Total OpEx"              in lines
        assert "Operating Profit (EBIT)" in lines


# =============================================================================
# CLASS 8: validation flags
# =============================================================================

class TestValidationFlags:

    def test_clean_data_raises_no_flags(self, flags):
        assert len(flags) == 0

    def test_forecast_row_count(self, full_df):
        assert len(full_df[full_df["type"] == "forecast"]) == 36

    def test_actual_row_count(self, full_df):
        assert len(full_df[full_df["type"] == "actual"]) == 108

    def test_no_negative_forecast_values(self, full_df):
        fc = full_df[full_df["type"] == "forecast"]
        assert (fc["value"] >= 0).all()

    def test_cogs_margin_under_100pct(self, full_df):
        fc = full_df[full_df["type"] == "forecast"]
        for period in fc["period"].unique():
            rev  = fc[(fc["period"]==period) & (fc["line_item"]=="Revenue")]["value"].iloc[0]
            cogs = fc[(fc["period"]==period) & (fc["line_item"]=="COGS")]["value"].iloc[0]
            assert cogs / rev < 1.0


# =============================================================================
# CLASS 9: output writing and audit trail
# =============================================================================

class TestOutputWriting:

    @pytest.fixture
    def mock_commentary(self):
        return (
            "FORECAST OVERVIEW\n"
            "H2 revenue is EUR 8,490,872 with EBIT of EUR 542,191.\n\n"
            "DRIVER COMMENTARY\n"
            "Revenue grows in line with the run rate.\n\n"
            "KEY RISKS AND RECOMMENDATIONS\n"
            "Watch the August dip.\n\n"
            "DATA FLAGS\nNo flags raised."
        )

    def test_text_file_created(self, mock_commentary, full_df, flags,
                               last_actual, forecast_periods, tmp_dirs):
        out_dir, audit_log = tmp_dirs
        path, _ = write_output(
            mock_commentary, full_df, flags, 1974, 1500, "end_turn",
            last_actual, forecast_periods
        )
        assert path.exists()
        assert path.stat().st_size > 100

    def test_audit_has_dual_hashes(self, mock_commentary, full_df, flags,
                                   last_actual, forecast_periods, tmp_dirs):
        out_dir, audit_log = tmp_dirs
        write_output(
            mock_commentary, full_df, flags, 1974, 1500, "end_turn",
            last_actual, forecast_periods
        )
        record = json.loads(audit_log.read_text(encoding="utf-8").strip())
        assert "actuals_hash" in record
        assert "driver_hash"  in record
        assert record["actuals_hash"].startswith("sha256:")
        assert record["driver_hash"].startswith("sha256:")
        assert record["actuals_hash"] != record["driver_hash"]

    def test_audit_forecast_fields(self, mock_commentary, full_df, flags,
                                   last_actual, forecast_periods, tmp_dirs):
        out_dir, audit_log = tmp_dirs
        write_output(
            mock_commentary, full_df, flags, 1974, 1500, "end_turn",
            last_actual, forecast_periods
        )
        record = json.loads(audit_log.read_text(encoding="utf-8").strip())
        assert record["last_actual"]    == "2026-06"
        assert record["forecast_start"] == "2026-07"
        assert record["forecast_end"]   == "2026-12"
        assert record["actuals_rows"]   == 108
        assert record["forecast_rows"]  == 36

    def test_clean_run_no_review_required(self, mock_commentary, full_df, flags,
                                          last_actual, forecast_periods, tmp_dirs):
        out_dir, audit_log = tmp_dirs
        write_output(
            mock_commentary, full_df, flags, 1974, 1500, "end_turn",
            last_actual, forecast_periods
        )
        record = json.loads(audit_log.read_text(encoding="utf-8").strip())
        assert record["requires_review"] is False

    def test_low_tokens_triggers_review(self, mock_commentary, full_df, flags,
                                        last_actual, forecast_periods, tmp_dirs):
        out_dir, audit_log = tmp_dirs
        write_output(
            mock_commentary, full_df, flags, 1974, 50, "end_turn",
            last_actual, forecast_periods
        )
        record = json.loads(audit_log.read_text(encoding="utf-8").strip())
        assert record["requires_review"] is True
