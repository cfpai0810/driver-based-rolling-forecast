# ================================================================
# config.py — Layer 1: All configuration for Project 2
# ================================================================

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise ValueError(
        "ANTHROPIC_API_KEY not found. "
        "Check that .env exists in the project root."
    )

MODEL      = "claude-sonnet-4-6"
MAX_TOKENS = 2048

BASE_DIR   = Path(__file__).parent
DATA_DIR   = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

ACTUALS_FILE = DATA_DIR / "actuals_ytd.csv"
DRIVER_FILE  = DATA_DIR / "driver_table.csv"
AUDIT_LOG    = OUTPUT_DIR / "audit_log.jsonl"

DEFAULT_ENTITY    = "Valencia Operations"
FORECAST_HORIZON = 6    # months to forecast forward

VALID_DRIVER_TYPES = [
    "seasonal_yoy",      # Revenue: annual YoY growth spread by derived seasonality
    "margin_pct",        # COGS: percentage of revenue
    "headcount_driven",  # Personnel: (existing + hires - attrition) x cost per head
    "cac_driven",        # Marketing: (new customers x CAC) + fixed campaign
    "growth_pct",        # R&D: month-on-month growth
    "fixed",             # IT: constant value
    "fixed_growth",      # retained for backward compatibility
]

# Input file paths for the richer driver model
OPERATIONAL_FILE = DATA_DIR / "operational_actuals.csv"
HEADCOUNT_FILE   = DATA_DIR / "headcount_schedule.csv"
CUSTOMER_FILE    = DATA_DIR / "customer_targets.csv"

# Validation thresholds for output sanity checks
MAX_COGS_MARGIN  = 1.0          # COGS cannot exceed 100% of Revenue
MAX_REVENUE      = 10_000_000   # flag if any single month exceeds this

# P&L structure — which line items are revenue, COGS, and operating expenses
REVENUE_ITEMS = ["Revenue"]
COGS_ITEMS    = ["COGS"]
OPEX_ITEMS    = ["Personnel Cost", "Marketing Spend", "IT Infrastructure", "R&D Expense"]
