# =============================================================================
# tests/test_pipeline.py — Project 2: Driver-Based Rolling Forecast Pipeline
# =============================================================================
# Phase 5: VALIDATE
#
# Run from the project root with (venv) active:
#   pytest tests/test_pipeline.py -v
#
# Fifteen test classes covering the full surface area of the pipeline:
#   1. Data loading            — all five input files load and validate
#   2. Seasonal derivation      — indices sum to 12, summer dip, Q4 peak
#   3. seasonal_yoy forecast     — trailing 12m, annual target, monthly spread
#   4. headcount_driven forecast — starting headcount, hires, attrition
#   5. cac_driven forecast       — new customers x CAC + fixed campaign
#   6. Simple drivers            — margin_pct, growth_pct, fixed
#   7. P&L roll-up               — Gross Profit, EBIT, margins, weakest month
#   8. Validation flags          — clean data, and the flag conditions
#   9. Output writing            — dual hashes, audit record, review logic
#  10. Driver overrides          — engine override parameter and guard
#  11. Driver controls mapping   — display/engine conversion, override builder
#  12. Commentary helpers        — fingerprint stability, section parsing, HTML
#  13. Shared output builders    — PDF/CSV bytes, data hashes, requires_review
#  14. Session audit record      — audit shape, drivers, overrides
#  15. Keyless example and diagrams — example fingerprint, commentary, SVG
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


# =============================================================================
# CLASS 10: driver_overrides engine extension
# =============================================================================

class TestDriverOverrides:

    def _run(self, actuals_df, drivers_df, operational_df, headcount_df,
             customer_df, last_actual, forecast_periods, seasonal_year,
             overrides):
        return calculate_forecast(
            actuals_df, drivers_df, operational_df, headcount_df, customer_df,
            last_actual, forecast_periods, seasonal_year,
            driver_overrides=overrides,
        )

    def test_none_matches_base(self, actuals_df, drivers_df, operational_df,
                               headcount_df, customer_df, last_actual,
                               forecast_periods, seasonal_year, full_df):
        """driver_overrides=None produces the same forecast as the base."""
        result_df, _, _ = self._run(
            actuals_df, drivers_df, operational_df, headcount_df,
            customer_df, last_actual, forecast_periods, seasonal_year, None)
        fc_base = full_df[full_df["type"] == "forecast"].reset_index(drop=True)
        fc_new  = result_df[result_df["type"] == "forecast"].reset_index(drop=True)
        pd.testing.assert_frame_equal(fc_base, fc_new)

    def test_scalar_override_changes_target_only(self, actuals_df, drivers_df,
                                                  operational_df, headcount_df,
                                                  customer_df, last_actual,
                                                  forecast_periods, seasonal_year,
                                                  full_df):
        """Higher R&D growth raises R&D, leaves the other five lines unchanged."""
        overrides = {"R&D Expense": {"method": "growth_pct", "value": 0.10}}
        result_df, _, _ = self._run(
            actuals_df, drivers_df, operational_df, headcount_df,
            customer_df, last_actual, forecast_periods, seasonal_year, overrides)
        fc_base = full_df[full_df["type"] == "forecast"]
        fc_new  = result_df[result_df["type"] == "forecast"]
        for p in forecast_periods:
            base_rd = fc_base[(fc_base["period"] == p) &
                              (fc_base["line_item"] == "R&D Expense")]["value"].iloc[0]
            new_rd  = fc_new[(fc_new["period"] == p) &
                             (fc_new["line_item"] == "R&D Expense")]["value"].iloc[0]
            assert new_rd > base_rd
        other_lines = ["Revenue", "COGS", "Personnel Cost",
                       "Marketing Spend", "IT Infrastructure"]
        for li in other_lines:
            for p in forecast_periods:
                base_val = fc_base[(fc_base["period"] == p) &
                                   (fc_base["line_item"] == li)]["value"].iloc[0]
                new_val  = fc_new[(fc_new["period"] == p) &
                                  (fc_new["line_item"] == li)]["value"].iloc[0]
                assert base_val == new_val, "{} {} changed".format(li, p)

    def test_method_switch_from_special_to_scalar(self, actuals_df, drivers_df,
                                                   operational_df, headcount_df,
                                                   customer_df, last_actual,
                                                   forecast_periods, seasonal_year):
        """Personnel switched from headcount_driven to fixed produces a flat line."""
        overrides = {"Personnel Cost": {"method": "fixed", "value": 300000}}
        result_df, _, _ = self._run(
            actuals_df, drivers_df, operational_df, headcount_df,
            customer_df, last_actual, forecast_periods, seasonal_year, overrides)
        fc = result_df[(result_df["type"] == "forecast") &
                       (result_df["line_item"] == "Personnel Cost")]
        assert len(fc) == len(forecast_periods)
        assert all(fc["value"] == 300000)

    def test_guard_rejects_non_native_special_method(self, actuals_df, drivers_df,
                                                      operational_df, headcount_df,
                                                      customer_df, last_actual,
                                                      forecast_periods, seasonal_year):
        """Setting a non-native line to headcount_driven or cac_driven raises."""
        with pytest.raises(ValueError, match="headcount_driven"):
            self._run(actuals_df, drivers_df, operational_df, headcount_df,
                      customer_df, last_actual, forecast_periods, seasonal_year,
                      {"Revenue": {"method": "headcount_driven", "value": 0}})
        with pytest.raises(ValueError, match="cac_driven"):
            self._run(actuals_df, drivers_df, operational_df, headcount_df,
                      customer_df, last_actual, forecast_periods, seasonal_year,
                      {"IT Infrastructure": {"method": "cac_driven", "value": 0}})

    def test_revenue_override_propagates_to_cogs_and_ebit(self, actuals_df,
                                                             drivers_df,
                                                             operational_df,
                                                             headcount_df,
                                                             customer_df,
                                                             last_actual,
                                                             forecast_periods,
                                                             seasonal_year,
                                                             full_df):
        """Higher Revenue flows through: COGS stays at 41.8% of NEW Revenue."""
        overrides = {"Revenue": {"method": "seasonal_yoy", "value": 0.25}}
        result_df, _, _ = self._run(
            actuals_df, drivers_df, operational_df, headcount_df,
            customer_df, last_actual, forecast_periods, seasonal_year, overrides)
        fc_base = full_df[full_df["type"] == "forecast"]
        fc_new  = result_df[result_df["type"] == "forecast"]
        for p in forecast_periods:
            new_rev  = fc_new[(fc_new["period"] == p) &
                              (fc_new["line_item"] == "Revenue")]["value"].iloc[0]
            base_rev = fc_base[(fc_base["period"] == p) &
                               (fc_base["line_item"] == "Revenue")]["value"].iloc[0]
            assert new_rev > base_rev
            new_cogs = fc_new[(fc_new["period"] == p) &
                              (fc_new["line_item"] == "COGS")]["value"].iloc[0]
            assert abs(new_cogs - new_rev * 0.418) < 1, \
                "COGS in {} not at 41.8%% of overridden Revenue".format(p)
            base_cogs = fc_base[(fc_base["period"] == p) &
                                (fc_base["line_item"] == "COGS")]["value"].iloc[0]
            assert new_cogs > base_cogs
        base_pnl = build_pnl(full_df, forecast_periods)
        new_pnl  = build_pnl(result_df, forecast_periods)
        base_ebit = float(base_pnl[base_pnl["line"] == "Operating Profit (EBIT)"]["total"].iloc[0])
        new_ebit  = float(new_pnl[new_pnl["line"] == "Operating Profit (EBIT)"]["total"].iloc[0])
        assert new_ebit > base_ebit

    def test_idempotent_override_matches_base(self, actuals_df, drivers_df,
                                               operational_df, headcount_df,
                                               customer_df, last_actual,
                                               forecast_periods, seasonal_year,
                                               full_df):
        """Restating Revenue at seasonal_yoy 0.12 produces the same forecast."""
        overrides = {"Revenue": {"method": "seasonal_yoy", "value": 0.12}}
        result_df, _, _ = self._run(
            actuals_df, drivers_df, operational_df, headcount_df,
            customer_df, last_actual, forecast_periods, seasonal_year, overrides)
        fc_base = full_df[full_df["type"] == "forecast"].reset_index(drop=True)
        fc_new  = result_df[result_df["type"] == "forecast"].reset_index(drop=True)
        pd.testing.assert_frame_equal(fc_base, fc_new)


# =============================================================================
# CLASS 11: Driver-controls mapping (Phase 4)
# =============================================================================

class TestDriverControlsMapping:
    """Pure-logic tests for the display/engine value conversion and the
    override builder. These cover the mapping layer between the Streamlit
    widgets and the engine's driver_overrides parameter."""

    def test_to_display_pct(self):
        from streamlit_app.lib.driver_controls import to_display
        assert to_display("seasonal_yoy", 0.12) == pytest.approx(12.0)
        assert to_display("growth_pct", 0.06) == pytest.approx(6.0)
        assert to_display("margin_pct", 0.418) == pytest.approx(41.8)

    def test_to_display_currency(self):
        from streamlit_app.lib.driver_controls import to_display
        assert to_display("fixed", 45000.0) == 45000.0

    def test_to_display_none_returns_zero(self):
        from streamlit_app.lib.driver_controls import to_display
        assert to_display("headcount_driven", None) == 0.0
        assert to_display("cac_driven", None) == 0.0

    def test_to_engine_pct(self):
        from streamlit_app.lib.driver_controls import to_engine
        assert to_engine("seasonal_yoy", 12.0) == pytest.approx(0.12)
        assert to_engine("growth_pct", 6.0) == pytest.approx(0.06)
        assert to_engine("margin_pct", 41.8) == pytest.approx(0.418)

    def test_to_engine_currency(self):
        from streamlit_app.lib.driver_controls import to_engine
        assert to_engine("fixed", 45000.0) == 45000.0

    def test_round_trip_pct(self):
        from streamlit_app.lib.driver_controls import to_display, to_engine
        for method in ("seasonal_yoy", "growth_pct", "margin_pct"):
            original = 0.12
            assert to_engine(method, to_display(method, original)) == pytest.approx(
                original)

    def test_build_overrides_excludes_schedule(self):
        from streamlit_app.lib.driver_controls import build_overrides
        state = {
            "Revenue": ("seasonal_yoy", 12.0),
            "Personnel Cost": ("headcount_driven", 0.0),
        }
        result = build_overrides(state)
        assert "Revenue" in result
        assert "Personnel Cost" not in result

    def test_build_overrides_all_schedule_returns_none(self):
        from streamlit_app.lib.driver_controls import build_overrides
        state = {
            "Personnel Cost": ("headcount_driven", 0.0),
            "Marketing Spend": ("cac_driven", 0.0),
        }
        assert build_overrides(state) is None

    def test_build_overrides_converts_pct_to_decimal(self):
        from streamlit_app.lib.driver_controls import build_overrides
        state = {"Revenue": ("seasonal_yoy", 15.0)}
        result = build_overrides(state)
        assert result["Revenue"]["method"] == "seasonal_yoy"
        assert result["Revenue"]["value"] == pytest.approx(0.15)

    def test_build_overrides_passes_currency_through(self):
        from streamlit_app.lib.driver_controls import build_overrides
        state = {"IT Infrastructure": ("fixed", 50000.0)}
        result = build_overrides(state)
        assert result["IT Infrastructure"]["value"] == 50000.0

    def test_full_state_produces_valid_overrides(self):
        """All six lines in default state produces overrides accepted by engine."""
        from streamlit_app.lib.driver_controls import build_overrides, to_display
        from streamlit_app.lib.driver_menu import LINE_DEFAULTS
        state = {}
        for line, dflt in LINE_DEFAULTS.items():
            state[line] = (dflt["method"],
                           to_display(dflt["method"], dflt["value"]))
        result = build_overrides(state)
        assert result is not None
        assert "Personnel Cost" not in result
        assert "Marketing Spend" not in result
        assert len(result) == 4

    def test_overrides_accepted_by_engine(self, actuals_df, drivers_df,
                                          operational_df, headcount_df,
                                          customer_df, last_actual,
                                          forecast_periods, seasonal_year):
        """Overrides built by build_overrides are accepted by the engine."""
        from streamlit_app.lib.driver_controls import build_overrides
        state = {
            "Revenue": ("seasonal_yoy", 15.0),
            "COGS": ("margin_pct", 40.0),
            "IT Infrastructure": ("fixed", 50000.0),
            "R&D Expense": ("growth_pct", 8.0),
        }
        overrides = build_overrides(state)
        full_df, _, flags = calculate_forecast(
            actuals_df, drivers_df, operational_df, headcount_df,
            customer_df, last_actual, forecast_periods, seasonal_year,
            driver_overrides=overrides,
        )
        fc = full_df[full_df["type"] == "forecast"]
        assert len(fc) == 6 * len(forecast_periods)
        assert len(flags) == 0


# =====================================================================
# 12. Forecast fingerprint and commentary helpers
# =====================================================================

class TestCommentary:
    """Phase 5: fingerprint stability, change detection, section parsing."""

    def test_fingerprint_stable(self, actuals_df, drivers_df, operational_df,
                                headcount_df, customer_df, last_actual,
                                forecast_periods, seasonal_year):
        """Same forecast produces the same fingerprint on repeated calls."""
        from streamlit_app.lib.commentary import forecast_fingerprint
        full_df, _, _ = calculate_forecast(
            actuals_df, drivers_df, operational_df, headcount_df,
            customer_df, last_actual, forecast_periods, seasonal_year,
        )
        pnl = build_pnl(full_df, forecast_periods)
        fp1 = forecast_fingerprint(pnl)
        fp2 = forecast_fingerprint(pnl)
        assert fp1 == fp2
        assert len(fp1) == 16

    def test_fingerprint_changes_with_override(self, actuals_df, drivers_df,
                                                operational_df, headcount_df,
                                                customer_df, last_actual,
                                                forecast_periods, seasonal_year):
        """A different driver assumption produces a different fingerprint."""
        from streamlit_app.lib.commentary import forecast_fingerprint
        full_base, _, _ = calculate_forecast(
            actuals_df, drivers_df, operational_df, headcount_df,
            customer_df, last_actual, forecast_periods, seasonal_year,
        )
        pnl_base = build_pnl(full_base, forecast_periods)
        fp_base = forecast_fingerprint(pnl_base)

        overrides = {"Revenue": {"method": "seasonal_yoy", "value": 0.25}}
        full_adj, _, _ = calculate_forecast(
            actuals_df, drivers_df, operational_df, headcount_df,
            customer_df, last_actual, forecast_periods, seasonal_year,
            driver_overrides=overrides,
        )
        pnl_adj = build_pnl(full_adj, forecast_periods)
        fp_adj = forecast_fingerprint(pnl_adj)

        assert fp_base != fp_adj

    def test_parse_sections_four_headers(self):
        """parse_sections extracts all four standard sections."""
        from streamlit_app.lib.commentary import parse_sections
        text = (
            "FORECAST OVERVIEW\nSome overview text.\n\n"
            "DRIVER COMMENTARY\n**Revenue:** Strong growth.\n\n"
            "KEY RISKS AND RECOMMENDATIONS\n- Watch margins.\n\n"
            "DATA FLAGS\nNo flags raised."
        )
        sections = parse_sections(text)
        assert len(sections) == 4
        assert "FORECAST OVERVIEW" in sections
        assert "DATA FLAGS" in sections
        assert "Strong growth" in sections["DRIVER COMMENTARY"]

    def test_parse_sections_missing_header(self):
        """parse_sections handles commentary missing a section gracefully."""
        from streamlit_app.lib.commentary import parse_sections
        text = "FORECAST OVERVIEW\nJust one section."
        sections = parse_sections(text)
        assert len(sections) == 1

    def test_section_to_html_bold(self):
        """section_to_html converts **bold** to <strong>."""
        from streamlit_app.lib.commentary import section_to_html
        html = section_to_html("The **key risk** is margin pressure.")
        assert "<strong>key risk</strong>" in html

    def test_section_to_html_bullets(self):
        """section_to_html converts bullet lines to <ul>/<li>."""
        from streamlit_app.lib.commentary import section_to_html
        html = section_to_html("- First item\n- Second item")
        assert "<ul>" in html
        assert "<li>First item</li>" in html
        assert "<li>Second item</li>" in html


# =====================================================================
# 13. Shared output builders (PDF, CSV, hashes, requires_review)
# =====================================================================

class TestSharedOutputBuilders:
    """Phase 6: shared builders produce valid output for both CLI and web."""

    def test_build_csv_bytes_matches_pnl(self, actuals_df, drivers_df,
                                          operational_df, headcount_df,
                                          customer_df, last_actual,
                                          forecast_periods, seasonal_year):
        """CSV bytes contain all P&L lines and the correct columns."""
        from src.step4_output_writer import build_csv_bytes
        full_df, _, _ = calculate_forecast(
            actuals_df, drivers_df, operational_df, headcount_df,
            customer_df, last_actual, forecast_periods, seasonal_year,
        )
        pnl = build_pnl(full_df, forecast_periods)
        csv_bytes = build_csv_bytes(pnl)
        text = csv_bytes.decode("utf-8")
        assert "Revenue" in text
        assert "Operating Profit (EBIT)" in text
        assert "line" in text.split("\n")[0]
        for p in forecast_periods:
            assert p in text

    def test_build_csv_bytes_is_bytes(self, actuals_df, drivers_df,
                                      operational_df, headcount_df,
                                      customer_df, last_actual,
                                      forecast_periods, seasonal_year):
        """build_csv_bytes returns bytes, not str."""
        from src.step4_output_writer import build_csv_bytes
        full_df, _, _ = calculate_forecast(
            actuals_df, drivers_df, operational_df, headcount_df,
            customer_df, last_actual, forecast_periods, seasonal_year,
        )
        pnl = build_pnl(full_df, forecast_periods)
        assert isinstance(build_csv_bytes(pnl), bytes)

    def test_build_pdf_bytes_without_commentary(self, actuals_df, drivers_df,
                                                 operational_df, headcount_df,
                                                 customer_df, last_actual,
                                                 forecast_periods, seasonal_year):
        """PDF builds successfully without commentary (keyless case)."""
        from src.step4_output_writer import build_pdf_bytes
        full_df, _, flags = calculate_forecast(
            actuals_df, drivers_df, operational_df, headcount_df,
            customer_df, last_actual, forecast_periods, seasonal_year,
        )
        pnl = build_pnl(full_df, forecast_periods)
        pdf = build_pdf_bytes(
            full_df, pnl, drivers_df, flags,
            last_actual, forecast_periods,
        )
        assert isinstance(pdf, bytes)
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 1000

    def test_build_pdf_bytes_with_commentary(self, actuals_df, drivers_df,
                                              operational_df, headcount_df,
                                              customer_df, last_actual,
                                              forecast_periods, seasonal_year):
        """PDF builds successfully with commentary and is larger."""
        from src.step4_output_writer import build_pdf_bytes
        full_df, _, flags = calculate_forecast(
            actuals_df, drivers_df, operational_df, headcount_df,
            customer_df, last_actual, forecast_periods, seasonal_year,
        )
        pnl = build_pnl(full_df, forecast_periods)
        commentary = (
            "FORECAST OVERVIEW\nH2 revenue is EUR 8.5m.\n\n"
            "DRIVER COMMENTARY\n**Revenue:** Growth assumption.\n\n"
            "KEY RISKS AND RECOMMENDATIONS\n- Watch margins.\n\n"
            "DATA FLAGS\nNo flags raised."
        )
        pdf_with = build_pdf_bytes(
            full_df, pnl, drivers_df, flags,
            last_actual, forecast_periods,
            commentary=commentary, tok_in=2500, tok_out=800,
        )
        pdf_without = build_pdf_bytes(
            full_df, pnl, drivers_df, flags,
            last_actual, forecast_periods,
        )
        assert pdf_with[:5] == b"%PDF-"
        assert len(pdf_with) > len(pdf_without)

    def test_compute_data_hashes(self):
        """Dual hashes are stable sha256 strings."""
        from src.step4_output_writer import compute_data_hashes
        ah, dh = compute_data_hashes()
        assert ah.startswith("sha256:")
        assert dh.startswith("sha256:")
        assert len(ah) == len("sha256:") + 64
        ah2, dh2 = compute_data_hashes()
        assert ah == ah2
        assert dh == dh2

    def test_check_requires_review_clean(self):
        """Clean run with sufficient output needs no review."""
        from src.step4_output_writer import check_requires_review
        assert not check_requires_review(
            [], stop_reason="end_turn", tok_out=800, has_commentary=True)

    def test_check_requires_review_flags(self):
        """Any data flags trigger review."""
        from src.step4_output_writer import check_requires_review
        assert check_requires_review(
            ["some flag"], stop_reason="end_turn", tok_out=800,
            has_commentary=True)

    def test_check_requires_review_truncated(self):
        """max_tokens stop reason triggers review."""
        from src.step4_output_writer import check_requires_review
        assert check_requires_review(
            [], stop_reason="max_tokens", tok_out=800, has_commentary=True)

    def test_check_requires_review_short_output(self):
        """Suspiciously short output triggers review."""
        from src.step4_output_writer import check_requires_review
        assert check_requires_review(
            [], stop_reason="end_turn", tok_out=50, has_commentary=True)

    def test_check_requires_review_no_commentary(self):
        """Without commentary, only flags trigger review."""
        from src.step4_output_writer import check_requires_review
        assert not check_requires_review([], has_commentary=False)
        assert check_requires_review(["flag"], has_commentary=False)


# =====================================================================
# 14. Session audit record
# =====================================================================

class TestAuditRecord:
    """Phase 6: audit record shape and requires_review integration."""

    def test_audit_record_shape(self, actuals_df, drivers_df, operational_df,
                                 headcount_df, customer_df, last_actual,
                                 forecast_periods, seasonal_year):
        """build_audit_record produces a dict with all required fields."""
        from streamlit_app.lib.audit import build_audit_record
        from streamlit_app.lib.commentary import forecast_fingerprint
        from src.step4_output_writer import compute_data_hashes
        full_df, _, flags = calculate_forecast(
            actuals_df, drivers_df, operational_df, headcount_df,
            customer_df, last_actual, forecast_periods, seasonal_year,
        )
        pnl = build_pnl(full_df, forecast_periods)
        fp = forecast_fingerprint(pnl)
        ah, dh = compute_data_hashes()
        rec = build_audit_record(
            eff_drivers_df=drivers_df,
            fingerprint=fp,
            actuals_hash=ah,
            driver_hash=dh,
            flags=flags,
            has_commentary=True,
            tok_in=2500,
            tok_out=800,
            stop_reason="end_turn",
        )
        assert "timestamp" in rec
        assert rec["fingerprint"] == fp
        assert rec["actuals_hash"] == ah
        assert rec["driver_hash"] == dh
        assert len(rec["effective_drivers"]) == 6
        assert rec["has_commentary"] is True
        assert rec["tokens_in"] == 2500
        assert rec["tokens_out"] == 800
        assert rec["requires_review"] is False
        assert rec["cost"] is not None
        assert rec["cost"]["eur"] > 0

    def test_audit_record_no_commentary(self, drivers_df):
        """Audit record without commentary has no cost or model."""
        from streamlit_app.lib.audit import build_audit_record
        rec = build_audit_record(
            eff_drivers_df=drivers_df,
            fingerprint="abc123",
            actuals_hash="sha256:aaa",
            driver_hash="sha256:bbb",
            flags=[],
            has_commentary=False,
        )
        assert rec["has_commentary"] is False
        assert rec["model"] is None
        assert rec["cost"] is None
        assert rec["requires_review"] is False

    def test_audit_drivers_reflect_overrides(self, drivers_df):
        """Effective drivers in audit reflect overrides."""
        from streamlit_app.lib.audit import build_audit_record
        df = drivers_df.copy()
        df.loc[df["line_item"] == "Revenue", "driver_type"] = "growth_pct"
        df.loc[df["line_item"] == "Revenue", "driver_value"] = 0.05
        rec = build_audit_record(
            eff_drivers_df=df,
            fingerprint="xyz",
            actuals_hash="sha256:aaa",
            driver_hash="sha256:bbb",
            flags=[],
            overrides={"Revenue": {"method": "growth_pct", "value": 0.05}},
        )
        rev = [d for d in rec["effective_drivers"]
               if d["line"] == "Revenue"][0]
        assert rev["method"] == "growth_pct"
        assert rec["overrides_applied"] is True


# =====================================================================
# 15. Keyless example and diagrams (Phase 7)
# =====================================================================

class TestKeylessExampleAndDiagrams:
    """Phase 7: example commentary, fingerprint match, and SVG diagrams."""

    def test_example_fingerprint_matches_base(self, actuals_df, drivers_df,
                                               operational_df, headcount_df,
                                               customer_df, last_actual,
                                               forecast_periods, seasonal_year):
        """The committed example fingerprint matches the base forecast."""
        from streamlit_app.lib.example_run import EXAMPLE
        from streamlit_app.lib.commentary import forecast_fingerprint
        full_df, _, _ = calculate_forecast(
            actuals_df, drivers_df, operational_df, headcount_df,
            customer_df, last_actual, forecast_periods, seasonal_year,
        )
        pnl = build_pnl(full_df, forecast_periods)
        assert forecast_fingerprint(pnl) == EXAMPLE["fingerprint"]

    def test_example_has_four_sections(self):
        """The example commentary parses into four standard sections."""
        from streamlit_app.lib.example_run import EXAMPLE
        from streamlit_app.lib.commentary import parse_sections
        sections = parse_sections(EXAMPLE["commentary"])
        assert len(sections) == 4
        for hdr in ("FORECAST OVERVIEW", "DRIVER COMMENTARY",
                    "KEY RISKS AND RECOMMENDATIONS", "DATA FLAGS"):
            assert hdr in sections

    def test_example_has_token_counts(self):
        """The example carries token counts and model name."""
        from streamlit_app.lib.example_run import EXAMPLE
        assert EXAMPLE["tokens_in"] > 0
        assert EXAMPLE["tokens_out"] > 0
        assert EXAMPLE["model"] == "claude-sonnet-4-6"

    def test_example_commentary_references_correct_figures(self):
        """The example commentary cites the base forecast's key figures."""
        from streamlit_app.lib.example_run import EXAMPLE
        text = EXAMPLE["commentary"]
        assert "8,490,872" in text
        assert "4,941,688" in text
        assert "542,191" in text

    def test_governance_flow_svg_valid(self):
        """governance_flow_svg returns a non-empty SVG string."""
        from streamlit_app.lib.governance_flow import governance_flow_svg
        svg = governance_flow_svg()
        assert "<svg" in svg
        assert "viewBox" in svg
        assert "YOU SET DRIVERS" in svg
        assert "YOU APPROVE" in svg

    def test_pipeline_flow_svg_valid(self):
        """pipeline_flow_svg returns a non-empty SVG string."""
        from streamlit_app.lib.pipeline_flow import pipeline_flow_svg
        svg = pipeline_flow_svg()
        assert "<svg" in svg
        assert "viewBox" in svg
        assert "Forecast" in svg
        assert "Commentary" in svg
        assert "deterministic" in svg

    def test_governance_lifecycle_svg_exists(self):
        """governance_lifecycle_svg returns a valid SVG (pre-existing)."""
        from streamlit_app.lib.governance_lifecycle import governance_lifecycle_svg
        svg = governance_lifecycle_svg()
        assert "<svg" in svg
        assert "YOU REVIEW" in svg
