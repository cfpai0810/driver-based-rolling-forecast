# Driver-Based Rolling Forecast

A six-month P&L forecast built from the drivers behind each line, with AI
commentary that explains the numbers without touching them.

**Live demo:** [driver-based-rolling-forecast.streamlit.app](https://driver-based-rolling-forecast.streamlit.app)

---

## What it does

Takes five inputs (financial actuals, operational actuals, a driver table,
a hiring plan, and customer acquisition targets), calculates a six-month
forward forecast in Python using six different driver methods, rolls the
result up into a simplified P&L, and uses the Claude API to write the
forward-looking commentary a CFO would expect.

The standout piece is the seasonality derivation: rather than assuming flat
month-on-month growth, Python derives the monthly seasonal pattern
automatically from last year's actuals and spreads an annual growth target
across the forecast months. This is the kind of work an analyst would
otherwise do by hand in a spreadsheet.

The Forecast page has two tabs. "View a worked example", open on arrival,
shows the base forecast with the commentary saved from a real run, so the
full output is visible without a key. "Run it yourself" lets you adjust
individual drivers and request a live AI commentary with your own
Anthropic API key. The result is a DRAFT until a named reviewer signs it
off in the page's Sign-off section.

**Outputs:** a text commentary, a chart-led A4 PDF report with quarterly
and monthly P&L tables, and a detailed P&L CSV export.

**Audit trail:** dual input hashes, the seasonality basis, and all three
output paths recorded on every run.

The data in this repository is illustrative sample data for a fictional entity.

---

## The design rule

Python produces every reported figure; the model writes the wording around it.

Every figure in the forecast tables and the CSV is traceable to a specific
calculation, not to the language model. This version does not check the
numbers in the model's wording, so read the tables for figures. The split
matters because language models are reliable at language and unreliable at
multi-step calculation.

---

## How the forecast is built

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
forward. Actuals are never overwritten. As each month closes in real use,
the boundary moves forward and the forecast window rolls with it.

---

## The six driver methods

Each line item uses the method that fits how it actually behaves. This is
how a real FP&A model is built: different lines use different logic.

| Line item | Driver method | How it works |
|-----------|--------------|--------------|
| Revenue | `seasonal_yoy` | Annual growth target spread across months using seasonality derived from last year |
| COGS | `margin_pct` | A percentage of each month's revenue |
| Personnel Cost | `headcount_driven` | (Starting headcount + hires - attrition) x fully loaded cost per head |
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
   December runs 23 per cent above the average month.
2. **Set an annual target.** The trailing twelve months of revenue is grown by
   the annual year-on-year assumption from the driver table.
3. **Spread it across the forecast.** The annual target is divided by twelve and
   multiplied by each month's seasonal index.

The result shows the real summer dip and Q4 build rather than a smooth upward
line, which materially changes the monthly profit picture.

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

The PDF presents this as a 24-period chart (actuals and forecast side by side),
a quarterly P&L table with actual/forecast tagging, and a month-by-month detail
table across all nine P&L lines. The full detailed P&L is also in the CSV
export.

---

## Human sign-off

When a run raises data flags, truncates, or returns an unusually short
response, the audit log sets `requires_review` to `true` and the pipeline
prints a review warning. After a person has checked the output, record the
sign-off with:

```bash
python review.py "Your Name"
```

This marks the most recent run as reviewed and records the reviewer name and a
timestamp back into the audit log. The AI does the heavy lifting; the person
stays accountable for what goes to the board.

On the web, the Forecast page ends with a Sign-off section once the forecast
has commentary. It lists the reasons for review as outstanding items; the
reviewer types a name and the word SIGN, and the result becomes FINAL: the PDF
carries "FINAL: signed off by NAME on D Month YYYY at HH:MM UTC" near the top
(a DRAFT carries "DRAFT: not signed off"), and the run's row in the session
audit carries the sign-off. A re-forecast that changes the figures, or new
commentary, is a new DRAFT.
The name and time are kept for the session only: they are not stored on the
server, and the name is not verified. The rule lives in `src/signoff.py`,
shared word for word across the series.

---

## How to run

### Web app

```bash
git clone https://github.com/cfpai0810/driver-based-rolling-forecast.git
cd driver-based-rolling-forecast
pip install -r requirements.txt
streamlit run streamlit_app/Home.py
```

The worked example runs without a key. To generate live AI commentary, paste
your own Anthropic API key into the sidebar.

### CLI pipeline

```bash
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
main.py                          CLI orchestrator
config.py                       Configuration and file paths
review.py                        Human review sign-off script
requirements.txt
LICENSE

src/
  step1_data_loader.py           Load and validate the five inputs
  step2_forecast_engine.py       Seasonality, six drivers, P&L roll-up
  step3_ai_engine.py             Build prompts, call Claude
  step4_output_writer.py         Text, PDF, CSV, audit log
  signoff.py                     The sign-off rule: a named reviewer types SIGN (DRAFT or FINAL)

streamlit_app/
  Home.py                        App shell and landing page
  lib/                           Theme, key gate, charts, cost, audit, errors
  views/
    how_the_model_works.py       Driver methods and seasonality explained
    forecast.py                  Live forecast with driver controls and sign-off
    your_own_data.py             Guide for running on your own numbers
    how_its_built.py             Trust story and technical depth

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
  bring_your_own_data.md         Guide for substituting your own data files

output/                          Generated files (gitignored)
tests/
  test_pipeline.py               152 tests
  test_signoff.py                9 tests: the sign-off rule
```

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
  "actuals_hash":    "sha256:e7bb8224d1e8...",
  "driver_hash":     "sha256:6439e704a7a4...",
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

161 tests, no real API calls:

```bash
pip install -r requirements-dev.txt
pytest tests -v
```

The tests cover data loading, seasonal derivation, all six driver methods,
the P&L roll-up, validation flags, output writing with the audit trail,
driver overrides and the driver controls, the commentary fingerprint and
section parsing, the PDF and CSV builders, the session audit record, the
worked example and the governance diagrams, the key gate, plain messages
for failed model calls, and the Home and Forecast pages (the worked example
button, the KPI tiles, the driver notes after an override, and the
tabular-figures rule in the theme), and the series look: the theme colour,
a banner on every page, the status chips, the Home blocks and page links,
the page titles and addresses, the tab order, the live run inside its own
tab and the browser tab icon; and the sign-off rule and the Sign-off section
from a run to FINAL. No test checks the charts.

---

## Tech stack

Python · pandas · Anthropic Claude API · python-dotenv · reportlab
(including reportlab.graphics for the chart) · Streamlit · hashlib · pytest

Tested on Python 3.13 and 3.14. numpy 2.5 needs Python 3.12 or later.

---

## Related projects

| # | Project | Status |
|---|---------|--------|
| 1 | AI Variance Commentary Engine | Complete |
| 2 | Driver-Based Rolling Forecast | This project |
| 3 | Anomaly Detection and Alert Agent | Complete |
| 4 | NL Scenario Modelling Copilot | Complete |
| 5 | Reconciliation and Tie-Out Assistant | Complete |
| 6 | Board Pack Generator | Complete |
| 7 | Planning-to-Warehouse-to-LLM Pipeline | Planned |
| 8 | 13-Week Cash Flow Forecasting Agent | Planned |
| 9 | Multi-Entity Consolidation and FX Engine | Planned |
| 10 | AI Governance Playbook | Planned |
