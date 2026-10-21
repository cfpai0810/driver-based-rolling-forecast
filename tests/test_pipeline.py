# =============================================================================
# tests/test_pipeline.py: Project 2: Driver-Based Rolling Forecast Pipeline
# =============================================================================
# Phase 5: VALIDATE
#
# Run from the project root with (venv) active:
#   pytest tests/test_pipeline.py -v
#
# The first fifteen test classes cover the pipeline itself:
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
# The classes after them cover the deployment pin and the review fixes: the
# key gate, plain messages for failed model calls, PDF text, the Home and
# Forecast pages, and the driver notes after an override.
#
# No real API calls are made. Where a test needs the model, a stand-in client
# plays it, so the suite needs no key and costs nothing.
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
        assert "YOU REVIEW" in svg
        assert "APPROVE" not in svg   # no approval step on the web

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


class TestDeploymentPins:
    """The web server stack the live app installs."""

    def test_item1_starlette_pinned_for_streamlit_1_60(self):
        """Streamlit 1.60 cannot serve images with starlette 1.8 or later (item 1)."""
        from importlib.metadata import version
        requirements = Path(__file__).resolve().parent.parent / "requirements.txt"
        assert "starlette==1.7.0" in requirements.read_text(encoding="utf-8-sig").split()
        if version("streamlit").startswith("1.60."):
            major, minor = (int(part) for part in version("starlette").split(".")[:2])
            assert (major, minor) < (1, 8)


# =====================================================================
# Step 2 fixes, bundle 1: key gate wording and persistence, audit
# caption, one plain message per failed model call
# =====================================================================

import httpx

APP_DIR = Path(__file__).resolve().parent.parent / "streamlit_app"
TEST_KEY = "sk-ant-api03-" + "x" * 90


def _sdk_error(cls, status):
    """A stand-in Anthropic SDK error built on a fake HTTP exchange."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("stand-in", response=httpx.Response(status, request=request),
               body=None)


class _StandInClient:
    """Plays the Anthropic client: raises the given error or returns the reply."""

    def __init__(self, exc=None, reply=None):
        self.messages = self
        self._exc = exc
        self._reply = reply

    def create(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return self._reply


def _app(page):
    from streamlit.testing.v1 import AppTest
    return AppTest.from_file(str(APP_DIR / page), default_timeout=180)


def _gate_on_two_pages():
    """A two-page stand-in app: the gate runs only when 'where' is 'gate'."""
    import streamlit as st
    from streamlit_app.lib.key_gate import render_key_gate
    if st.session_state.get("where", "gate") == "gate":
        st.session_state["live_client"] = render_key_gate()
    else:
        st.write("Another page, without the key gate.")


class TestStep2KeyGateAndErrors:
    """Items 2, 3, 4, 17 and 55."""

    def test_item17_each_failed_call_maps_to_one_plain_message(self):
        import anthropic
        from streamlit_app.lib.errors import (
            failure_code, friendly_message, model_failure_message,
        )
        cases = [
            (_sdk_error(anthropic.AuthenticationError, 401), "key_rejected"),
            (_sdk_error(anthropic.PermissionDeniedError, 403), "key_forbidden"),
            (_sdk_error(anthropic.NotFoundError, 404), "model_not_found"),
            (_sdk_error(anthropic.RateLimitError, 429), "rate_limited"),
            (_sdk_error(anthropic.BadRequestError, 400), "bad_request"),
            (_sdk_error(anthropic.InternalServerError, 500), "service_unavailable"),
            (_sdk_error(anthropic.APIStatusError, 529), "service_unavailable"),
            (anthropic.APIConnectionError(request=httpx.Request(
                "POST", "https://api.anthropic.com/v1/messages")),
             "service_unavailable"),
        ]
        for exc, code in cases:
            assert failure_code(exc) == code
            message = friendly_message(exc)
            assert message == model_failure_message(code)
            assert message.endswith("Code: `{}`".format(code))
            assert type(exc).__name__ not in message
            assert "Traceback" not in message
        for code in ("bad_request", "model_not_found"):
            assert "usually temporary" not in model_failure_message(code)

    def test_item17_wrapped_sdk_error_still_maps(self):
        import anthropic
        from streamlit_app.lib.errors import failure_code, friendly_message
        try:
            try:
                raise _sdk_error(anthropic.AuthenticationError, 401)
            except anthropic.AuthenticationError as exc:
                raise RuntimeError("engine wrap") from exc
        except RuntimeError as wrapped:
            assert failure_code(wrapped) == "key_rejected"
            assert "RuntimeError" not in friendly_message(wrapped)

    def test_item17_other_failures_read_plainly(self):
        from streamlit_app.lib.claude_client import NoKeyError
        from streamlit_app.lib.errors import failure_code, friendly_message
        assert failure_code(ValueError("x")) is None
        generic = friendly_message(ValueError("x"))
        no_key = friendly_message(NoKeyError("x"))
        for message in (generic, no_key):
            assert "ValueError" not in message and "NoKeyError" not in message
            assert "example prompts" not in message
            assert "key above" not in message
        assert "sidebar" in no_key

    def test_item55_forecast_page_shows_one_plain_message(self):
        import anthropic
        from streamlit_app.lib.errors import model_failure_message
        at = _app("pages/forecast.py")
        at.session_state["live_client"] = _StandInClient(
            exc=_sdk_error(anthropic.AuthenticationError, 401))
        at.run()
        next(b for b in at.button if b.label == "Write commentary").click().run()
        assert not at.exception
        shown = [e.value for e in at.error]
        assert shown == [model_failure_message("key_rejected")]
        assert "AuthenticationError" not in shown[0]
        assert "_commentary_text" not in at.session_state

    def test_item55_reply_without_text_is_one_plain_message(self):
        from types import SimpleNamespace
        from streamlit_app.lib.errors import model_failure_message
        empty = SimpleNamespace(
            content=[], stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=10, output_tokens=0))
        at = _app("pages/forecast.py")
        at.session_state["live_client"] = _StandInClient(reply=empty)
        at.run()
        next(b for b in at.button if b.label == "Write commentary").click().run()
        assert not at.exception
        assert [e.value for e in at.error] == [
            model_failure_message("unreadable_reply")]
        assert "_commentary_text" not in at.session_state

    def test_item2_key_gate_privacy_wording(self):
        from streamlit_app.lib.errors import KEY_LOOKS_COMPLETE
        at = _app("Home.py")
        at.run()
        key_input = at.sidebar.text_input(key="byo_api_key")
        assert key_input.help == ("Held in the server's memory for this session "
                                  "only. Never stored, never logged.")
        sidebar_text = " ".join(m.value for m in at.sidebar.markdown)
        assert ("Your key is held in the server's memory for your session only, "
                "used to make the call, and never stored or logged.") in sidebar_text
        assert "browser" not in sidebar_text.lower()
        key_input.input(TEST_KEY).run()
        assert [s.value for s in at.sidebar.success] == [KEY_LOOKS_COMPLETE]
        header = (APP_DIR / "lib" / "key_gate.py").read_text(encoding="utf-8")
        assert "never stored server-side" not in header
        assert "browser" not in header.lower()

    def test_item3_audit_caption_says_where_the_trail_is_held(self):
        at = _app("pages/forecast.py")
        at.run()
        captions = " ".join(c.value for c in at.caption)
        assert ("This audit trail is held in the server's session state and "
                "cleared when your session ends.") in captions
        assert "browser" not in captions.lower()
        assert "never stored on any server" not in captions

    def test_item4_key_survives_a_run_without_the_gate(self):
        """A run that does not reach the key input (an interrupted run during a
        page change, or a page without the gate) makes Streamlit drop the
        input's own state. The key must still be in effect afterwards."""
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_function(_gate_on_two_pages, default_timeout=60)
        at.run()
        at.sidebar.text_input(key="byo_api_key").input(TEST_KEY).run()
        assert at.session_state["live_client"] is not None
        at.session_state["where"] = "elsewhere"
        at.run()
        at.session_state["where"] = "gate"
        at.run()
        assert not at.exception
        assert at.sidebar.text_input(key="byo_api_key").value == TEST_KEY
        assert at.session_state["live_client"] is not None

    def test_item4_kept_key_seeds_the_input(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_function(_gate_on_two_pages, default_timeout=60)
        at.session_state["anthropic_api_key"] = TEST_KEY
        at.run()
        assert not at.exception
        assert at.sidebar.text_input(key="byo_api_key").value == TEST_KEY
        assert at.session_state["live_client"] is not None


# =====================================================================
# Step 2 fixes, bundle 2: growth revenue keeps COGS, PDF text, CLI cost
# currency, KPI tiles at phone width, sidebar state on arrival
# =====================================================================

def _pdf_drawn_text(pdf):
    """The text-drawing operators of a reportlab PDF, inflated (stdlib only)."""
    import base64
    import re
    import zlib
    parts = []
    for raw in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        data = raw.strip()
        if data.endswith(b"~>"):
            data = data[:-2]
        try:
            parts.append(zlib.decompress(base64.a85decode(data)).decode("latin-1"))
        except Exception:
            continue
    # reportlab draws a character that came from an entity (the & of R&D) as
    # its own string; join neighbouring strings so words read whole
    return re.sub(r"\)\s*Tj\s*\(", "", "\n".join(parts))


class TestStep2ForecastAndOutputs:
    """Items 5, 28, 35, 57, 30 and 53."""

    def test_item5_growth_revenue_keeps_cogs(self, actuals_df, drivers_df,
                                             operational_df, headcount_df,
                                             customer_df, last_actual,
                                             forecast_periods, seasonal_year):
        overrides = {"Revenue": {"method": "growth_pct", "value": 0.02}}
        full, _, flags = calculate_forecast(
            actuals_df, drivers_df, operational_df, headcount_df,
            customer_df, last_actual, forecast_periods, seasonal_year,
            driver_overrides=overrides,
        )
        assert not [f for f in flags if f.startswith("CALCULATION_ORDER")]
        pnl = build_pnl(full, forecast_periods).set_index("line")
        cogs_ratio = float(drivers_df.loc[
            drivers_df["line_item"] == "COGS", "driver_value"].iloc[0])
        for p in forecast_periods:
            revenue = pnl.loc["Revenue", p]
            assert revenue > 0
            assert pnl.loc["COGS", p] > 0
            assert pnl.loc["Gross Profit", p] / revenue == pytest.approx(
                1 - cogs_ratio, abs=1e-6)

    def test_item28_model_text_with_markup_characters_builds_a_pdf(
            self, full_df, pnl_df, drivers_df, flags, last_actual,
            forecast_periods):
        from src.step4_output_writer import build_pdf_bytes
        commentary = (
            "FORECAST OVERVIEW\nMargin < 60% & falling; see <b and R&D.\n\n"
            "DRIVER COMMENTARY\n**Revenue:** growth <b>bold</b> & more < less.\n\n"
            "KEY RISKS AND RECOMMENDATIONS\n- **P&L** risk < 5% > 2%.\n\n"
            "DATA FLAGS\nNo flags raised."
        )
        pdf = build_pdf_bytes(
            full_df, pnl_df, drivers_df, ["NEGATIVE_VALUE: R&D Expense <test>"],
            last_actual, forecast_periods, commentary=commentary,
            tok_in=1742, tok_out=612,
        )
        assert pdf[:5] == b"%PDF-"
        text = _pdf_drawn_text(pdf)
        assert "R&D Expense" in text
        assert "R&D;" not in text and "P&L;" not in text
        assert "<b and R&D." in text

    def test_item28_pdf_text_helper_escapes_ampersand_first(self):
        from src.step4_output_writer import pdf_text
        assert pdf_text("R&D <b> & P&L >") == (
            "R&amp;D &lt;b&gt; &amp; P&amp;L &gt;")

    def test_item28_pdf_has_no_dashes_and_reads_r_and_d(
            self, full_df, pnl_df, drivers_df, flags, last_actual,
            forecast_periods, headcount_df, customer_df):
        from src.step4_output_writer import build_pdf_bytes
        pdf = build_pdf_bytes(
            full_df, pnl_df, drivers_df, flags, last_actual, forecast_periods,
            headcount_df=headcount_df, customer_df=customer_df,
        )
        text = _pdf_drawn_text(pdf)
        assert "R&D;" not in text and "P&L;" not in text
        assert "DETAILED MONTHLY P&L" in text
        assert "Revenue and EBIT, full timeline" in text
        assert "ROLLING FORECAST: " in text
        # no em or en dash drawn, in any of the forms reportlab can write one
        for dash in ("\\227", "\\226", "\x97", "\x96", "\N{EM DASH}", "\N{EN DASH}"):
            assert dash not in text

    def test_item35_growth_driver_shows_as_a_percentage(self, drivers_df):
        from src.step4_output_writer import _driver_table
        table = _driver_table(drivers_df)
        cells = {row[0].text: row[2].text for row in table._cellvalues[1:]}
        assert cells["Revenue"] == "12.0%"
        assert cells["R&amp;D Expense"] == "6.0%"

    def test_item35_web_pdf_failure_keeps_the_csv(self):
        at = _app("pages/forecast.py")
        with patch("src.step4_output_writer.build_pdf_bytes",
                   side_effect=RuntimeError("stand-in failure")):
            at.run()
        assert not at.exception
        shown = [e.value for e in at.error]
        assert len(shown) == 1 and shown[0].startswith(
            "The PDF report could not be built.")
        assert "RuntimeError" not in shown[0] and "stand-in" not in shown[0]
        labels = [d.proto.label for d in at.get("download_button")]
        assert labels == ["Download CSV"]

    def test_item57_cli_cost_line_names_the_currency_it_computes(self, capsys):
        from types import SimpleNamespace
        import src.step3_ai_engine as engine
        reply = SimpleNamespace(
            content=[SimpleNamespace(text="FORECAST OVERVIEW\nStand-in.")],
            usage=SimpleNamespace(input_tokens=1_000_000, output_tokens=0),
            stop_reason="end_turn",
        )
        with patch.object(engine, "client", _StandInClient(reply=reply)):
            engine.call_claude("system", "user")
        line = next(l for l in capsys.readouterr().out.splitlines()
                    if "Approx cost" in l)
        # one million input tokens at USD 3 per million
        assert line.split(":", 1)[1].split() == ["USD", "3.0000"]

    def test_item30_kpi_tiles_wrap_at_phone_width(self):
        at = _app("pages/forecast.py")
        at.run()
        rows = [m.value for m in at.markdown if "display:flex" in m.value]
        assert len(rows) == 2
        for html in rows:
            assert "display:flex;flex-wrap:wrap" in html
            assert html.count("flex:1 1 180px;min-width:0") == 3

    def test_item53_sidebar_state_is_auto(self):
        import ast
        tree = ast.parse((APP_DIR / "Home.py").read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", "") == "set_page_config"]
        assert len(calls) == 1
        kwargs = {k.arg: ast.literal_eval(k.value) for k in calls[0].keywords}
        assert kwargs["initial_sidebar_state"] == "auto"


# =====================================================================
# Step 2 fixes, bundle 3: key gate in an expander, a Home button to the
# worked example, tabular figures only on numeric elements
# =====================================================================

class TestStep2HomeAndTheme:
    """UX1, UX2 and UX4."""

    GATE_LABEL = "Run it live with your own key (optional)"

    def test_ux1_key_gate_sits_in_a_closed_expander(self):
        at = _app("Home.py")
        at.run()
        gates = [e for e in at.sidebar.expander if e.label == self.GATE_LABEL]
        assert len(gates) == 1
        gate = gates[0]
        assert gate.proto.expanded is False
        assert gate.text_input(key="byo_api_key").label == "Anthropic API key"
        inside = " ".join(m.value for m in gate.markdown) + " ".join(
            c.value for c in gate.caption)
        assert "bills your Anthropic account" in inside
        assert "held in the server's memory" in inside
        headings = " ".join(m.value for m in at.sidebar.markdown)
        assert "Run it yourself" not in headings
        below = [c.value for c in at.sidebar.caption if c.value.startswith("Live mode")]
        assert below == ["Live mode is off. The worked examples need no key."]

        gate.text_input(key="byo_api_key").input("sk-ant-short").run()
        gate = next(e for e in at.sidebar.expander if e.label == self.GATE_LABEL)
        assert len(gate.warning) == 1
        gate.text_input(key="byo_api_key").input(TEST_KEY).run()
        gates = [e for e in at.sidebar.expander if e.label == self.GATE_LABEL]
        assert len(gates) == 1
        below = [c.value for c in at.sidebar.caption if c.value.startswith("Live mode")]
        assert below == ["Live mode is on for this session."]

    def test_ux2_home_button_opens_the_worked_example(self):
        at = _app("Home.py")
        at.run()
        assert "byo_api_key" not in at.session_state or not at.session_state[
            "byo_api_key"]
        labels = [b.label for b in at.button]
        assert labels[0] == "See the worked example"
        at.button[0].click().run()
        assert not at.exception
        assert "View a worked example" in [t.label for t in at.tabs]
        assert "Saved example (base forecast, default drivers)." in [
            c.value for c in at.caption]
        assert any("FORECAST OVERVIEW" in m.value for m in at.markdown)

    def test_ux4_tabular_figures_only_on_numeric_elements(self):
        import re
        from streamlit_app.lib.theme import inject_css
        css = inject_css()
        rules = re.findall(r"([^{}]+)\{\{?([^}]*)\}", css)
        global_rule = next(body for sel, body in rules if "html, body" in sel)
        assert "font-family" in global_rule
        assert "tnum" not in global_rule and '"cv05" 1' in global_rule
        numeric = [sel for sel, body in rules if "tnum" in body]
        assert len(numeric) == 1
        selectors = [s.strip() for s in numeric[0].split("*/")[-1].split(",")]
        for wanted in ("table", "table *", '[data-testid="stMetricValue"]',
                       '[data-testid="stMetricDelta"]', ".sc-kpi-figure"):
            assert wanted in selectors

    def test_ux4_kpi_figures_carry_the_numeric_class(self):
        at = _app("pages/forecast.py")
        at.run()
        rows = [m.value for m in at.markdown if "display:flex" in m.value]
        assert len(rows) == 2
        for html in rows:
            assert html.count('class="sc-kpi-figure"') >= 3


# =====================================================================
# Step 3: the Home button opens the worked example tab (UX2)
# =====================================================================

def _tab_containers(node):
    """Every tab container under an AppTest node, in page order."""
    found = []
    for child in getattr(node, "children", {}).values():
        if getattr(child, "type", None) == "tab_container":
            found.append(child)
        found.extend(_tab_containers(child))
    return found


class TestStep3WorkedExampleTab:
    """UX2: Home's button lands on the example tab; the sidebar link does not."""

    def test_ux2_button_opens_the_example_tab(self):
        at = _app("Home.py")
        at.run()
        assert at.button[0].label == "See the worked example"
        at.button[0].click().run()
        assert not at.exception
        assert [t.label for t in at.tabs] == [
            "Run it yourself", "View a worked example"]
        tab_sets = _tab_containers(at.main)
        assert len(tab_sets) == 1
        assert tab_sets[0].proto.tab_container.default_tab_index == 1
        # the flag is one-off: the page took it
        assert "forecast_open_example" not in at.session_state
        assert "Saved example (base forecast, default drivers)." in [
            c.value for c in at.caption]

    def test_ux2_sidebar_link_still_opens_the_first_tab(self):
        at = _app("pages/forecast.py")
        at.run()
        assert not at.exception
        tab_sets = _tab_containers(at.main)
        assert len(tab_sets) == 1
        assert tab_sets[0].proto.tab_container.default_tab_index == 0


# =====================================================================
# Step 3 fixes: the PDF driver table, and driver notes after an override
# =====================================================================

class _PromptKeeper:
    """Plays the Anthropic client: keeps what it was sent, returns a reply."""

    def __init__(self):
        self.messages = self
        self.sent = None

    def create(self, **kwargs):
        from types import SimpleNamespace
        self.sent = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(text="FORECAST OVERVIEW\nStand-in.")],
            usage=SimpleNamespace(input_tokens=1742, output_tokens=612),
            stop_reason="end_turn",
        )


def _driver_rows(drivers_df):
    """The PDF driver table as {line item: (driver type, assumption, note)}."""
    from src.step4_output_writer import _driver_table
    table = _driver_table(drivers_df)
    return {row[0].text.replace("&amp;", "&"):
            tuple(cell.text.replace("&amp;", "&") for cell in row[1:])
            for row in table._cellvalues[1:]}


class TestStep3Fixes:
    """The PDF driver table reads plainly; an override replaces a stale note."""

    def test_fix_pdf_driver_table(self, full_df, pnl_df, drivers_df, flags,
                                  last_actual, forecast_periods):
        import re
        from src.step4_output_writer import build_pdf_bytes
        rows = _driver_rows(drivers_df)
        assert {line: row[:2] for line, row in rows.items()} == {
            "Revenue":           ("Seasonal YoY growth", "12.0%"),
            "COGS":              ("Margin % of revenue", "41.8%"),
            "Personnel Cost":    ("Headcount schedule", "Hiring schedule"),
            "Marketing Spend":   ("Customer acquisition schedule",
                                  "Customer schedule"),
            "IT Infrastructure": ("Fixed amount", "EUR 45,000"),
            "R&D Expense":       ("Month-on-month growth", "6.0%"),
        }
        text = _pdf_drawn_text(build_pdf_bytes(
            full_df, pnl_df, drivers_df, flags, last_actual, forecast_periods))
        assert "Seasonal YoY growth" in text and "Hiring schedule" in text
        assert not re.search(r"EUR 0(?![\d.,])", text)
        for code in ("seasonal_yoy", "margin_pct", "headcount_driven",
                     "cac_driven", "growth_pct"):
            assert code not in text

    def test_fix_notes_after_override(self):
        import src.step4_output_writer as writer
        real_build = writer.build_pdf_bytes
        built = {}

        def keep_pdf(*args, **kwargs):
            built["drivers"] = args[2]
            built["pdf"] = real_build(*args, **kwargs)
            return built["pdf"]

        client = _PromptKeeper()
        at = _app("pages/forecast.py")
        with patch("src.step4_output_writer.build_pdf_bytes", side_effect=keep_pdf):
            at.run()
            at.number_input(key="value_r&d_expense").set_value(10.0)
            at.number_input(key="value_revenue").set_value(15.0)
            next(b for b in at.button if b.label == "Re-forecast").click().run()
            at.session_state["live_client"] = client
            at.run()
            next(b for b in at.button if b.label == "Write commentary").click().run()
        assert not at.exception

        # The prompt: the overridden lines state the new value, marked as
        # overridden; the lines left at their CSV value keep their notes
        prompt = client.sent["messages"][0]["content"]
        block = prompt.split("<driver_assumptions>")[1].split(
            "</driver_assumptions>")[0]
        lines = {l.split("|")[0].strip(): l for l in block.strip().splitlines()}
        assert lines["R&D Expense"].endswith(
            "| Overridden in the app: Month-on-month growth at 10.0%")
        assert lines["Revenue"].endswith(
            "| Overridden in the app: Seasonal YoY growth at 15.0%")
        assert lines["COGS"].endswith("| 41.8% of revenue")
        assert lines["IT Infrastructure"].endswith(
            "| Fixed contract through Dec 2026")
        for old in ("6%", "6.0%", "12%", "12.0%"):
            assert old not in lines["R&D Expense"] + lines["Revenue"]
        assert "6% MoM investment ramp" not in prompt
        assert "12% annual YoY growth" not in prompt
        assert "Annual growth assumption:   15%" in prompt

        # The PDF: the same notes, and neither line states 6% or 12%
        rows = _driver_rows(built["drivers"])
        assert rows["R&D Expense"] == (
            "Month-on-month growth", "10.0%",
            "Overridden in the app: Month-on-month growth at 10.0%")
        assert rows["Revenue"] == (
            "Seasonal YoY growth", "15.0%",
            "Overridden in the app: Seasonal YoY growth at 15.0%")
        assert rows["COGS"][2] == "41.8% of revenue"
        for old in ("6%", "6.0%", "12%", "12.0%"):
            assert old not in " ".join(rows["R&D Expense"] + rows["Revenue"])
        text = _pdf_drawn_text(built["pdf"])
        assert "6% MoM investment ramp" not in text
        assert "12% annual YoY growth" not in text
        assert "Overridden in the app: Month-on-month growth at 10.0%" in text


class TestDependencies:
    """The pinned packages (items 21 and 22): test tools only in the dev file,
    no byte order mark, one anthropic version, patched versions."""

    @staticmethod
    def _pins(name):
        text = (Path(__file__).resolve().parent.parent / name).read_text(encoding="utf-8-sig")
        pins = {}
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-r")) and "==" in line:
                package, version = line.split("==", 1)
                pins[package.strip().lower()] = version.strip()
        return text, pins

    @staticmethod
    def _version(text):
        return tuple(int(part) for part in text.split(".")[:3])

    def test_item21_test_tools_only_in_dev_requirements(self):
        _, runtime = self._pins("requirements.txt")
        dev_text, dev = self._pins("requirements-dev.txt")
        assert not {"pytest", "pluggy", "iniconfig", "pygments", "colorama"} & set(runtime)
        assert "-r requirements.txt" in dev_text and "pytest" in dev

    def test_item21_no_byte_order_mark(self):
        root = Path(__file__).resolve().parent.parent
        for name in ("requirements.txt", "requirements-dev.txt"):
            assert not (root / name).read_bytes().startswith(b"\xef\xbb\xbf"), name

    def test_item21_one_anthropic_version(self):
        assert self._pins("requirements.txt")[1]["anthropic"] == "0.116.0"

    def test_item22_patched_versions(self):
        pins = self._pins("requirements.txt")[1]
        assert self._version(pins["anyio"]) >= (4, 14, 2)
        assert self._version(pins["pillow"]) >= (12, 3, 0)

    def test_item22_certifi_has_the_fixed_root_bundle(self):
        # certifi before 2026.10.18 trusts emSign ECC Root CA G3, whose
        # intermediates had compromised keys (GHSA-6q48-6c7w-9gw2).
        text = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text(
            encoding="utf-8-sig")
        assert "certifi==2026.10.19" in text.split()
