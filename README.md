# Driver-Based Rolling Forecast Pipeline

A practical demonstration of how AI can be leveraged to automate a
traditionally manual, spreadsheet-heavy finance task: building a monthly
rolling forecast from operational drivers and writing the board-ready
commentary that goes with it.

---

## What it does

Takes five inputs (financial actuals, operational actuals, a driver table,
a hiring plan, and customer acquisition targets), calculates a 6-month
forward forecast in Python using six different driver methods, rolls the
result up into a simplified P&L, and uses the Claude API to write the
forward-looking commentary a CFO would expect.

The standout piece is the seasonality derivation: rather than assuming
flat month-on-month growth, Python derives the monthly seasonal pattern
automatically from last year's actuals and spreads an annual growth target
across the forecast months. This is the kind of work an analyst would
otherwise do by hand in a spreadsheet.

**Outputs:** a text commentary, a chart-led A4 PDF report, and a detailed
P&L CSV export.
**Audit trail:** dual input hashes, the seasonality basis, and all three
output paths recorded on every run.

---

## The six driver methods

Each line item uses the method that fits how it actually behaves. This is
how a real FP&A model is built. Different lines use different logic.

| Line item | Driver method | How it works |
|-----------|--------------|--------------|
| Revenue | `seasonal_yoy` | Annual growth target spread across months using seasonality derived from last year |
| COGS | `margin_pct` | A percentage of each month's revenue |
| Personnel Cost | `headcount_driven` | (Starting headcount + hires - attrition) x fully-loaded cost per head |
| Marketing Spend | `cac_driven` | (Target new customers x cost to acquire) + fixed campaign budget |
| IT Infrastructure | `fixed` | A constant monthly contract |
| R&D Expense | `growth_pct` | Month-on-month compounding growth |

---

## The seasonality method

Real businesses are seasonal. Revenue dips in summer and peaks in Q4. A flat
growth assumption misses this entirely. The pipeline handles it in three steps,
all in Python:

1. **Derive the seasonal shape.** For the most recent complete calendar year,
   each month's revenue is divided by the average month. This produces twelve
   seasonal indices that always sum to 12.0. A December index of 1.23 means
   December runs 23% above the average month.
2. **Set an annual target.** The trailing twelve months of revenue is grown by
   the annual year-on-year assumption from the driver table.
3. **Spread it across the forecast.** The annual target is divided by twelve and
   multiplied by each month's seasonal index.

The result shows the real summer dip and Q4 build rather than a smooth upward
line, which materially changes the monthly profit picture.

---

## How to run

Clone and install:

```bash
git clone https://github.com/cfpai0810/driver-based-rolling-forecast.git
cd driver-based-rolling-forecast
python -m venv venv
venv\Scripts\Activate.ps1        # Windows PowerShell
pip install -r requirements.txt
```

Add your Anthropic API key to a `.env` file:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Run:

```bash
python main.py
```

The pipeline writes three files to `output/`: a text commentary, a PDF report,
and a P&L CSV.

---

## Project structure

```
main.py                          Orchestrator
config.py                        Layer 1: configuration and file paths
review.py                        Human review sign-off script
requirements.txt

src/
  step1_data_loader.py           Layer 2: load and validate the five inputs
  step2_forecast_engine.py       Layer 3: seasonality, six drivers, P&L roll-up
  step3_ai_engine.py             Layer 4: build prompts, call Claude
  step4_output_writer.py         Layer 5: text, PDF, CSV, audit log

data/
  actuals_ytd.csv                18 months of financial actuals (EUR)
  operational_actuals.csv        Headcount and new customers (from HR and CRM)
  driver_table.csv               One driver method per line item
  headcount_schedule.csv         Forward hiring plan
  customer_targets.csv           Forward acquisition targets

docs/
  sample_forecast.pdf            Example PDF report
  sample_pnl.csv                 Example P&L export
  sample_output.txt              Example text commentary

output/                          Generated files (gitignored)
tests/
  test_pipeline.py               52 assertions across 9 test classes
```

---

## Architecture

**Core design rule:** Python calculates every number. Claude only interprets
and narrates. Every figure in the forecast is traceable to a specific
calculation, not to the language model.

```
Five CSV inputs
      |
      v
step1_data_loader.py     Load and validate actuals, drivers, operational data,
                         hiring plan, customer targets. Detect the boundary
                         between locked actuals and the forecast window.
      |
      v
step2_forecast_engine.py Derive seasonality. Apply each line item's driver.
                         Roll the result up into a simplified P&L.
      |
      v
step3_ai_engine.py       Build the prompt with the P&L, seasonality, headcount
                         build and CAC detail. Call Claude for the commentary.
      |
      v
step4_output_writer.py   Write the text commentary, the PDF report, the P&L
                         CSV, and one audit record per run.
```

The forecast starts from the boundary (the last locked actual) and rolls
forward. Actuals are never overwritten. As each month closes in real use, the
boundary moves forward and the forecast window rolls with it.

---

## The simplified P&L

The forecast rolls up into the standard management accounts structure:

```
Revenue
less COGS
= Gross Profit
less Operating Expenses (Personnel + Marketing + IT + R&D)
= Operating Profit (EBIT)
```

The PDF presents this as a chart (Revenue and EBIT by month) plus a compact
KPI table with monthly columns and three summary columns: YTD (actuals booked
this year), YTG (forecast remaining), and FY (the full year). The full detailed
P&L is in the CSV export.

---

## Human review and sign-off

When a run raises data flags, truncates, or returns an unusually short
response, the audit log sets `requires_review` to `true` and the pipeline
prints a review warning. After a person has checked the output, record the
sign-off with:

```bash
python review.py "Your Name"
```

This marks the most recent run as reviewed and records the reviewer name and a
timestamp back into the audit log. The AI does the heavy lifting; the person
stays accountable for what goes to the Board.

---

## Audit trail

Every run appends one record to `output/audit_log.jsonl`:

```json
{
  "run_id":          "2026-07-08T15:42:48+00:00",
  "project":         "rolling-forecast-pipeline",
  "entity":          "Valencia Operations",
  "last_actual":     "2026-06",
  "forecast_start":  "2026-07",
  "forecast_end":    "2026-12",
  "horizon_months":  6,
  "seasonal_year":   2025,
  "actuals_rows":    108,
  "forecast_rows":   36,
  "actuals_hash":    "sha256:4fa8a4ef6b49...",
  "driver_hash":     "sha256:db506b9cacc8...",
  "output_file":     "output/forecast_commentary_2026-07-08.txt",
  "pdf_file":        "output/forecast_commentary_2026-07-08.pdf",
  "csv_file":        "output/forecast_pnl_2026-07-08.csv",
  "model":           "claude-sonnet-4-6",
  "input_tokens":    1895,
  "output_tokens":   1157,
  "stop_reason":     "end_turn",
  "flags_raised":    [],
  "human_reviewed":  false,
  "requires_review": false
}
```

Two separate hashes, one for the financial actuals and one for the driver
table, mean it is always possible to tell which input changed between runs.
The `seasonal_year` field records which year's seasonality shaped the forecast,
so any run is fully reproducible.

---

## Test suite

52 assertions across 9 test classes. No real API calls. Runs in a few seconds:

```bash
pytest tests/test_pipeline.py -v
```

The classes cover data loading, seasonal derivation, all six driver methods,
the P&L roll-up, validation flags, and output writing with the audit trail.

---

## Tech stack

Python 3.11 · pandas · Anthropic Claude API · python-dotenv · reportlab
(including reportlab.graphics for the chart) · hashlib · pytest

---

## Related projects

| # | Project | Status |
|---|---------|--------|
| 1 | AI Variance Commentary Engine | Complete |
| 2 | Driver-Based Rolling Forecast Pipeline | Complete |
| 3 | Anomaly Detection and Alert Agent | Planned |
| 4 | NL Scenario Modelling Copilot | Planned |
| 5 | Budget Challenge Assistant | Planned |
| 6 | Agentic Board Pack Generator | Planned |
| 7 | Anaplan to Snowflake to LLM Pipeline | Planned |
| 8 | Cuenta y Cocina Live AI Finance | Planned |
| 9 | AI Governance Playbook | Planned |
