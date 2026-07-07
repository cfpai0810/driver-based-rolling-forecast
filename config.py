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

VALID_DRIVER_TYPES = ["growth_pct", "margin_pct", "fixed_growth", "fixed"]

# Validation thresholds for output sanity checks
MAX_COGS_MARGIN    = 1.0    # COGS cannot exceed 100% of Revenue
MAX_REVENUE        = 10_000_000  # flag if any single month exceeds this
