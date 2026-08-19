# =============================================================================
# step4_output_writer.py — Layer 5: Output Writing and Audit Trail
# =============================================================================
# Responsibilities:
#   - write_output(): write commentary to timestamped text file + audit log
#
# write_pdf() and export_forecast_csv() are added in later steps.
#
# This layer knows about: file paths, audit logs, timestamps
# This layer does NOT know about: Claude, prompts, forecast calculation logic
# =============================================================================

import json
import hashlib
import re
from pathlib import Path
from datetime import datetime, timezone

from reportlab.lib.pagesizes import A4
from reportlab.lib.units     import cm
from reportlab.lib           import colors
from reportlab.lib.styles    import ParagraphStyle
from reportlab.lib.enums     import TA_CENTER, TA_RIGHT
from reportlab.platypus      import (
    SimpleDocTemplate, Paragraph, Spacer,
    HRFlowable, Table, TableStyle, KeepTogether
)
from reportlab.graphics.shapes import (
    Drawing, Line, Rect, String, Circle, PolyLine
)

from config import (
    OUTPUT_DIR,
    AUDIT_LOG,
    ACTUALS_FILE,
    DRIVER_FILE,
    DEFAULT_ENTITY,
    MODEL,
    FORECAST_HORIZON,
    REVENUE_ITEMS,
    COGS_ITEMS,
    OPEX_ITEMS,
)

REVENUE_ITEMS_LOCAL = REVENUE_ITEMS
COGS_ITEMS_LOCAL    = COGS_ITEMS
OPEX_ITEMS_LOCAL    = OPEX_ITEMS

# ── Page geometry and colour palette (same system as Project 1) ───────────────
PAGE_W = A4[0] - 4 * cm

DARK_BLUE  = colors.HexColor("#1A3A5C")
MID_BLUE   = colors.HexColor("#2D6A9F")
LIGHT_BLUE = colors.HexColor("#EAF2FB")
FLAG_RED   = colors.HexColor("#A32D2D")
FLAG_BG    = colors.HexColor("#FFF0F0")
AMBER      = colors.HexColor("#854F0B")
AMBER_BG   = colors.HexColor("#FAEEDA")
GREEN      = colors.HexColor("#1D6B0F")
BODY_DARK  = colors.HexColor("#1A1A19")
MUTED      = colors.HexColor("#898781")
RULE_COLOR = colors.HexColor("#D3D1C7")
ROW_ALT    = colors.HexColor("#F8F7F2")
TBL_HEADER = colors.HexColor("#E6F1FB")

S_BODY    = ParagraphStyle("Body",   fontName="Helvetica", fontSize=10,
                textColor=BODY_DARK, leading=16)
S_META    = ParagraphStyle("Meta",   fontName="Helvetica", fontSize=8,
                textColor=MUTED, leading=13, alignment=TA_CENTER)
S_TBL     = ParagraphStyle("Tbl",    fontName="Helvetica", fontSize=8,
                textColor=BODY_DARK, leading=10)
S_TBL_HDR = ParagraphStyle("TblHdr", fontName="Helvetica-Bold", fontSize=8,
                textColor=DARK_BLUE, leading=10)
S_TBL_NUM = ParagraphStyle("TblNum", fontName="Helvetica", fontSize=8,
                textColor=BODY_DARK, leading=10, alignment=TA_RIGHT)

S_TBL_SM     = ParagraphStyle("TblSm",    fontName="Helvetica",      fontSize=7,
                textColor=BODY_DARK, leading=9)
S_TBL_SM_HDR = ParagraphStyle("TblSmHdr", fontName="Helvetica-Bold", fontSize=7,
                textColor=DARK_BLUE, leading=9)
S_TBL_SM_NUM = ParagraphStyle("TblSmNum", fontName="Helvetica",      fontSize=7,
                textColor=BODY_DARK, leading=9, alignment=TA_RIGHT)

EM = "—"   # em dash


def compute_data_hashes():
    """SHA-256 hashes of the two input files (actuals and driver table).

    Both the CLI audit and the web audit need these; computing them once
    here keeps the hash format identical.
    """
    with open(ACTUALS_FILE, "rb") as f:
        actuals_hash = "sha256:" + hashlib.sha256(f.read()).hexdigest()
    with open(DRIVER_FILE, "rb") as f:
        driver_hash = "sha256:" + hashlib.sha256(f.read()).hexdigest()
    return actuals_hash, driver_hash


def check_requires_review(flags, stop_reason=None, tok_out=0,
                          has_commentary=False):
    """Determine whether a forecast run needs human review.

    Shared between the CLI audit and the web audit so the triggers
    are identical.
    """
    if len(flags) > 0:
        return True
    if not has_commentary:
        return False
    if stop_reason == "max_tokens":
        return True
    if tok_out < 200:
        return True
    return False


def clean_markdown(text):
    """Convert Claude markdown to ReportLab-safe XML."""
    text = text.replace("&", "&amp;")
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'^#{1,3}\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^---+\s*$',   '', text, flags=re.MULTILINE)
    text = re.sub(r'^\*\s+',      '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def parse_forecast_sections(commentary):
    """
    Parse Claude commentary into four named sections:
    forecast_overview, driver_commentary, key_risks, data_flags
    """
    commentary = clean_markdown(commentary)
    sections = {
        "forecast_overview":  "",
        "driver_commentary":  "",
        "key_risks":          "",
        "data_flags":         "",
    }
    markers = {
        "forecast_overview": "FORECAST OVERVIEW",
        "driver_commentary": "DRIVER COMMENTARY",
        "key_risks":         "KEY RISKS AND RECOMMENDATIONS",
        "data_flags":        "DATA FLAGS",
    }
    text = commentary.strip()
    positions = {}
    for key, marker in markers.items():
        idx = text.find(marker)
        if idx != -1:
            positions[key] = idx
    if not positions:
        sections["forecast_overview"] = text
        return sections
    sorted_keys = sorted(positions, key=lambda k: positions[k])
    for i, key in enumerate(sorted_keys):
        start = positions[key] + len(markers[key])
        end   = positions[sorted_keys[i + 1]] if i + 1 < len(sorted_keys) else len(text)
        sections[key] = text[start:end].strip()
    return sections


def _cover_block(entity, last_actual, forecast_periods, ts,
                 tok_in=0, tok_out=0, nflags=0, has_commentary=True):
    """Full-width dark blue cover block."""
    if has_commentary:
        subtitle = '{}  ·  Last actual: {}  ·  AI Generated  ·  {}'.format(
            entity, last_actual, MODEL)
        meta = 'Generated {}  ·  {:,}/{:,} tokens  ·  {} flag(s)'.format(
            ts[:10], tok_in, tok_out, nflags)
    else:
        subtitle = '{}  ·  Last actual: {}  ·  Driver-based forecast'.format(
            entity, last_actual)
        meta = 'Generated {}  ·  {} flag(s)'.format(ts[:10], nflags)
    rows = [
        [Paragraph(
            '<font color="white"><b>ROLLING FORECAST — {} TO {}</b></font>'.format(
                forecast_periods[0], forecast_periods[-1]),
            ParagraphStyle("CT", fontName="Helvetica-Bold", fontSize=16,
                textColor=colors.white, alignment=TA_CENTER)
        )],
        [Paragraph(
            '<font color="#AACCEE">{}</font>'.format(subtitle),
            ParagraphStyle("CS", fontName="Helvetica", fontSize=9,
                textColor=colors.HexColor("#AACCEE"), alignment=TA_CENTER)
        )],
        [Paragraph(
            '<font color="#6699BB">{}</font>'.format(meta),
            ParagraphStyle("CM", fontName="Helvetica", fontSize=8,
                textColor=colors.HexColor("#6699BB"), alignment=TA_CENTER)
        )],
    ]
    t = Table(rows, colWidths=[PAGE_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), DARK_BLUE),
        ("TOPPADDING",    (0, 0), (0, 0),   18),
        ("BOTTOMPADDING", (0, 0), (0, 0),   6),
        ("TOPPADDING",    (0, 1), (0, 1),   4),
        ("BOTTOMPADDING", (0, 1), (0, 1),   4),
        ("TOPPADDING",    (0, 2), (0, 2),   4),
        ("BOTTOMPADDING", (0, 2), (0, 2),   14),
        ("LEFTPADDING",   (0, 0), (-1, -1), 20),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 20),
    ]))
    return t


def _section_header(title):
    """Full-width mid-blue section header band."""
    t = Table([[Paragraph(
        '<font color="white"><b>{}</b></font>'.format(title),
        ParagraphStyle("SH", fontName="Helvetica-Bold", fontSize=11,
            textColor=colors.white, leading=14)
    )]], colWidths=[PAGE_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), MID_BLUE),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def _forecast_table(full_df, line_items):
    """
    Period-by-period pivot table. One row per period, one column per
    line item. Forecast rows shaded light blue to distinguish from
    actuals. Period label includes 'A' or 'F' suffix.
    """
    all_periods = sorted(full_df["period"].unique())

    label_col = 2.4 * cm
    remaining = PAGE_W - label_col
    item_col  = remaining / len(line_items)
    cw = [label_col] + [item_col] * len(line_items)

    # Abbreviate long line item names for the header row
    short_names = {
        "Marketing Spend":   "Marketing",
        "Headcount Cost":    "Headcount",
        "IT Infrastructure": "IT Infra",
        "R&D Expense":       "R&D",
    }
    headers = ["Period"] + [short_names.get(li, li) for li in line_items]
    header_row = [Paragraph("<b>{}</b>".format(h), S_TBL_HDR) for h in headers]
    table_rows = [header_row]

    for period in all_periods:
        period_data = full_df[full_df["period"] == period]
        ptype = period_data["type"].iloc[0]
        label = "{} {}".format(period, "A" if ptype == "actual" else "F")
        row_cells = [Paragraph(label, S_TBL)]
        for li in line_items:
            match = period_data[period_data["line_item"] == li]
            val   = match["value"].iloc[0] if len(match) else None
            row_cells.append(Paragraph(
                "{:,.0f}".format(val) if val is not None else EM,
                S_TBL_NUM
            ))
        table_rows.append(row_cells)

    style = [
        ("BACKGROUND",    (0, 0), (-1, 0),  TBL_HEADER),
        ("LINEBELOW",     (0, 0), (-1, 0),  1,   MID_BLUE),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("LINEBELOW",     (0, 1), (-1, -1), 0.5, RULE_COLOR),
    ]
    for i, period in enumerate(all_periods, start=1):
        ptype = full_df[full_df["period"] == period]["type"].iloc[0]
        if ptype == "forecast":
            style.append(("BACKGROUND", (0, i), (-1, i), LIGHT_BLUE))
        elif i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))

    t = Table(table_rows, colWidths=cw)
    t.setStyle(TableStyle(style))
    return t


def _driver_table(drivers_df):
    """Compact driver assumptions table: Line Item | Driver Type | Assumption | Note."""
    cw = [3.2*cm, 2.6*cm, 2.2*cm, PAGE_W - 8.0*cm]
    rows = [[
        Paragraph("<b>Line item</b>",   S_TBL_HDR),
        Paragraph("<b>Driver type</b>", S_TBL_HDR),
        Paragraph("<b>Assumption</b>",  S_TBL_HDR),
        Paragraph("<b>Note</b>",        S_TBL_HDR),
    ]]
    for _, row in drivers_df.iterrows():
        dtype = row["driver_type"]
        dval  = row["driver_value"]
        if dtype in ("growth_pct", "margin_pct", "fixed_growth"):
            val_str = "{:.1%}".format(dval)
        else:
            val_str = "EUR {:,.0f}".format(dval)
        note = row.get("note", "") if "note" in row.index else ""
        rows.append([
            Paragraph(row["line_item"], S_TBL),
            Paragraph(dtype,            S_TBL),
            Paragraph(val_str,          S_TBL_NUM),
            Paragraph(note,             S_TBL),
        ])
    style = [
        ("BACKGROUND",    (0, 0), (-1, 0),  TBL_HEADER),
        ("LINEBELOW",     (0, 0), (-1, 0),  1,   MID_BLUE),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("LINEBELOW",     (0, 1), (-1, -1), 0.5, RULE_COLOR),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    t = Table(rows, colWidths=cw)
    t.setStyle(TableStyle(style))
    return t


def _headcount_schedule_table(headcount_df):
    """Compact headcount hiring plan table."""
    mn = {"01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
          "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
          "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec"}
    cw = [1.8 * cm, 1.8 * cm, 2.0 * cm, 3.0 * cm]
    rows = [[
        Paragraph("<b>Period</b>", S_TBL_HDR),
        Paragraph("<b>New hires</b>", S_TBL_HDR),
        Paragraph("<b>Attrition</b>", S_TBL_HDR),
        Paragraph("<b>Cost / head (ann.)</b>", S_TBL_HDR),
    ]]
    for _, r in headcount_df.iterrows():
        p = r["period"]
        rows.append([
            Paragraph("{} {}".format(mn.get(p.split("-")[1], ""), p[:4]),
                      S_TBL),
            Paragraph("{:,.0f}".format(r["new_hires"]), S_TBL_NUM),
            Paragraph("{:.1%}".format(r["attrition_rate"]), S_TBL_NUM),
            Paragraph("EUR {:,.0f}".format(r["cost_per_head_annual"]),
                      S_TBL_NUM),
        ])
    style = [
        ("BACKGROUND",    (0, 0), (-1, 0), TBL_HEADER),
        ("LINEBELOW",     (0, 0), (-1, 0), 1, MID_BLUE),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("LINEBELOW",     (0, 1), (-1, -1), 0.5, RULE_COLOR),
    ]
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    t = Table(rows, colWidths=cw)
    t.setStyle(TableStyle(style))
    return t


def _customer_targets_table(customer_df):
    """Compact customer acquisition targets table."""
    mn = {"01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
          "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
          "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec"}
    cw = [1.8 * cm, 2.4 * cm, 1.8 * cm, 2.4 * cm]
    rows = [[
        Paragraph("<b>Period</b>", S_TBL_HDR),
        Paragraph("<b>New customers</b>", S_TBL_HDR),
        Paragraph("<b>CAC</b>", S_TBL_HDR),
        Paragraph("<b>Fixed campaign</b>", S_TBL_HDR),
    ]]
    for _, r in customer_df.iterrows():
        p = r["period"]
        rows.append([
            Paragraph("{} {}".format(mn.get(p.split("-")[1], ""), p[:4]),
                      S_TBL),
            Paragraph("{:,.0f}".format(r["target_new_customers"]),
                      S_TBL_NUM),
            Paragraph("EUR {:,.0f}".format(r["cac"]), S_TBL_NUM),
            Paragraph("EUR {:,.0f}".format(r["fixed_campaign"]),
                      S_TBL_NUM),
        ])
    style = [
        ("BACKGROUND",    (0, 0), (-1, 0), TBL_HEADER),
        ("LINEBELOW",     (0, 0), (-1, 0), 1, MID_BLUE),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("LINEBELOW",     (0, 1), (-1, -1), 0.5, RULE_COLOR),
    ]
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    t = Table(rows, colWidths=cw)
    t.setStyle(TableStyle(style))
    return t


def _flag_box(text, severity="error"):
    """Full-width coloured flag box — reused from Project 1 pattern."""
    bg = FLAG_BG  if severity == "error" else AMBER_BG
    tc = FLAG_RED if severity == "error" else AMBER
    t = Table([[Paragraph(
        '<b>[!]</b>  {}'.format(text),
        ParagraphStyle("FB", fontName="Helvetica", fontSize=9,
            textColor=tc, leading=13)
    )]], colWidths=[PAGE_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bg),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def update_audit_pdf(pdf_path):
    """Update the most recent audit log record with the PDF output path."""
    if not AUDIT_LOG.exists():
        return
    lines = AUDIT_LOG.read_text(encoding="utf-8").strip().split("\n")
    if not lines or not lines[-1].strip():
        return
    last_record = json.loads(lines[-1])
    last_record["pdf_file"] = str(pdf_path)
    lines[-1] = json.dumps(last_record)
    AUDIT_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_audit_csv(csv_path):
    """
    Update the most recent audit log record with the P&L CSV path.

    Called by export_pnl_csv() after the CSV is written. Mirrors
    update_audit_pdf() so the audit trail records all three outputs:
    the text commentary, the PDF report, and the P&L CSV export.
    """
    if not AUDIT_LOG.exists():
        return
    lines = AUDIT_LOG.read_text(encoding="utf-8").strip().split("\n")
    if not lines or not lines[-1].strip():
        return
    last_record            = json.loads(lines[-1])
    last_record["csv_file"] = str(csv_path)
    lines[-1]              = json.dumps(last_record)
    AUDIT_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_output(commentary, full_df, flags, tok_in, tok_out,
                 stop_reason, last_actual, forecast_periods, seasonal_year=None):
    """
    Write commentary to a timestamped text file and append one JSONL
    audit record per run.

    Two separate SHA256 hashes are recorded — one for the actuals file
    and one for the driver table — so it is always possible to tell
    which input changed between runs.

    Args:
        commentary:        string returned by call_claude()
        full_df:            DataFrame with actual + forecast rows
        flags:               list of validation flag strings
        tok_in, tok_out:     token counts from call_claude()
        stop_reason:         stop reason string from call_claude()
        last_actual:         string — last locked period
        forecast_periods:    list of forecast period strings

    Returns:
        output_path:  Path to the written commentary text file
        audit_record: dict — the record just written to the audit log
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

    actuals_hash, driver_hash = compute_data_hashes()
    requires_review = check_requires_review(
        flags, stop_reason, tok_out, has_commentary=True,
    )

    audit_record = {
        "run_id":           ts_log,
        "project":          "rolling-forecast-pipeline",
        "entity":           DEFAULT_ENTITY,
        "last_actual":      last_actual,
        "forecast_start":   forecast_periods[0],
        "forecast_end":     forecast_periods[-1],
        "horizon_months":   FORECAST_HORIZON,
        "seasonal_year":    seasonal_year,
        "actuals_rows":     len(full_df[full_df["type"] == "actual"]),
        "forecast_rows":    len(full_df[full_df["type"] == "forecast"]),
        "actuals_hash":     actuals_hash,
        "driver_hash":      driver_hash,
        "output_file":      str(output_path),
        "pdf_file":         None,
        "csv_file":         None,
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


def _kpi_chart(full_df, last_actual, forecast_periods, pnl_df, width, height):
    """
    Dual-axis chart: Revenue as bars (left axis), EBIT as line (right axis).
    Shows the full timeline (actuals + forecast) with a boundary marker.
    """
    d = Drawing(width, height)

    all_periods = sorted(full_df["period"].unique())
    revenue = []
    ebit = []
    for p in all_periods:
        pdf = full_df[full_df["period"] == p]
        rev = float(pdf[pdf["line_item"].isin(REVENUE_ITEMS_LOCAL)]["value"].sum())
        cogs = float(pdf[pdf["line_item"].isin(COGS_ITEMS_LOCAL)]["value"].sum())
        opex = float(pdf[pdf["line_item"].isin(OPEX_ITEMS_LOCAL)]["value"].sum())
        revenue.append(rev)
        ebit.append(rev - cogs - opex)

    ml, mr, mt, mb = 55, 55, 30, 40
    plot_w = width - ml - mr
    plot_h = height - mt - mb
    n = len(all_periods)

    rev_max = max(revenue) * 1.15 if revenue else 1
    ebit_max = max(ebit) * 1.25 if max(ebit) > 0 else 1

    month_names = {"01": "J", "02": "F", "03": "M", "04": "A",
                   "05": "M", "06": "J", "07": "J", "08": "A",
                   "09": "S", "10": "O", "11": "N", "12": "D"}

    d.add(String(width / 2, height - 16,
        "Revenue and EBIT {} full timeline".format(EM),
        fontName="Helvetica-Bold", fontSize=10, fillColor=DARK_BLUE,
        textAnchor="middle"))

    slot = plot_w / n
    bar_w = slot * 0.55

    boundary_idx = all_periods.index(last_actual)
    boundary_x = ml + (boundary_idx + 1) * slot

    d.add(Rect(ml, mb, boundary_x - ml, plot_h,
               fillColor=colors.HexColor("#F0F6FC"),
               strokeColor=None, strokeWidth=0))
    d.add(Line(boundary_x, mb, boundary_x, mb + plot_h,
               strokeColor=RULE_COLOR, strokeWidth=0.75,
               strokeDashArray=[3, 3]))
    mid_a = ml + (boundary_x - ml) / 2
    mid_f = boundary_x + (ml + plot_w - boundary_x) / 2
    d.add(String(mid_a, mb + plot_h - 10, "Actuals",
        fontName="Helvetica", fontSize=7, fillColor=MUTED,
        textAnchor="middle"))
    d.add(String(mid_f, mb + plot_h - 10, "Forecast",
        fontName="Helvetica", fontSize=7, fillColor=MUTED,
        textAnchor="middle"))

    for i, rev in enumerate(revenue):
        x = ml + i * slot + (slot - bar_w) / 2
        bh = (rev / rev_max) * plot_h
        d.add(Rect(x, mb, bar_w, bh, fillColor=LIGHT_BLUE,
            strokeColor=MID_BLUE, strokeWidth=0.6))

    pts = []
    for i, e in enumerate(ebit):
        x = ml + i * slot + slot / 2
        y = mb + (e / ebit_max) * plot_h
        pts.extend([x, y])
    if len(pts) >= 4:
        d.add(PolyLine(pts, strokeColor=GREEN, strokeWidth=1.8))
    for i, e in enumerate(ebit):
        x = ml + i * slot + slot / 2
        y = mb + (e / ebit_max) * plot_h
        d.add(Circle(x, y, 2, fillColor=GREEN,
            strokeColor=colors.white, strokeWidth=0.5))

    for i, p in enumerate(all_periods):
        x = ml + i * slot + slot / 2
        lbl = month_names.get(p.split("-")[1], "")
        d.add(String(x, mb - 12, lbl,
            fontName="Helvetica", fontSize=6, fillColor=BODY_DARK,
            textAnchor="middle"))
        if p.endswith("-01") or p == all_periods[0]:
            d.add(String(x, mb - 21, p[:4],
                fontName="Helvetica", fontSize=6, fillColor=MUTED,
                textAnchor="middle"))

    d.add(String(ml - 8, height - mt + 2, "Revenue",
        fontName="Helvetica", fontSize=7, fillColor=MID_BLUE,
        textAnchor="end"))
    d.add(String(ml - 5, mb - 2, "0",
        fontName="Helvetica", fontSize=7, fillColor=MUTED,
        textAnchor="end"))
    d.add(String(ml - 5, mb + plot_h - 4,
        "{:.1f}M".format(rev_max / 1e6),
        fontName="Helvetica", fontSize=7, fillColor=MUTED,
        textAnchor="end"))

    d.add(String(width - mr + 8, height - mt + 2, "EBIT",
        fontName="Helvetica", fontSize=7, fillColor=GREEN,
        textAnchor="start"))
    d.add(String(width - mr + 5, mb - 2, "0",
        fontName="Helvetica", fontSize=7, fillColor=MUTED,
        textAnchor="start"))
    d.add(String(width - mr + 5, mb + plot_h - 4,
        "{:.0f}k".format(ebit_max / 1e3),
        fontName="Helvetica", fontSize=7, fillColor=MUTED,
        textAnchor="start"))

    d.add(Line(ml, mb, ml, mb + plot_h,
        strokeColor=RULE_COLOR, strokeWidth=0.5))
    d.add(Line(width - mr, mb, width - mr, mb + plot_h,
        strokeColor=RULE_COLOR, strokeWidth=0.5))
    d.add(Line(ml, mb, width - mr, mb,
        strokeColor=RULE_COLOR, strokeWidth=0.5))

    return d


def _compact_kpi_table(pnl_df, full_df, forecast_periods):
    """
    Compact KPI table: months as columns, headline KPIs as rows.
    Rows: Revenue, Gross Profit, EBIT, EBIT margin.
    Columns: each forecast month, then three summary columns:
      YTD    actuals booked so far this year (Jan to Jun 2026)
      YTG    forecast remaining this year (Jul to Dec 2026)
      FY     full year = YTD + YTG
    """
    fcst_year = forecast_periods[0].split("-")[0]
    ytd_periods = sorted(
        full_df[
            (full_df["type"] == "actual") &
            (full_df["period"].str.startswith(fcst_year))
        ]["period"].unique()
    )

    def actual_sum(items, periods):
        d = full_df[
            (full_df["type"] == "actual") &
            (full_df["line_item"].isin(items)) &
            (full_df["period"].isin(periods))
        ]
        return float(d["value"].sum())

    rev_row  = pnl_df[pnl_df["line"] == "Revenue"].iloc[0]
    gp_row   = pnl_df[pnl_df["line"] == "Gross Profit"].iloc[0]
    ebit_row = pnl_df[pnl_df["line"] == "Operating Profit (EBIT)"].iloc[0]

    # YTD (actuals booked this year)
    ytd_rev  = actual_sum(REVENUE_ITEMS_LOCAL, ytd_periods)
    ytd_cogs = actual_sum(COGS_ITEMS_LOCAL, ytd_periods)
    ytd_opex = actual_sum(OPEX_ITEMS_LOCAL, ytd_periods)
    ytd_gp   = ytd_rev - ytd_cogs
    ytd_ebit = ytd_gp - ytd_opex

    # YTG (forecast remaining this year)
    ytg_rev  = float(rev_row["total"])
    ytg_gp   = float(gp_row["total"])
    ytg_ebit = float(ebit_row["total"])

    # FY (full year = YTD + YTG)
    fy_rev   = ytd_rev  + ytg_rev
    fy_gp    = ytd_gp   + ytg_gp
    fy_ebit  = ytd_ebit + ytg_ebit

    month_names = {"07":"Jul","08":"Aug","09":"Sep","10":"Oct","11":"Nov","12":"Dec",
                   "01":"Jan","02":"Feb","03":"Mar","04":"Apr","05":"May","06":"Jun"}

    label_col = 2.6 * cm
    summary_w = 1.85 * cm
    month_w   = (PAGE_W - label_col - 3*summary_w) / len(forecast_periods)
    cw = [label_col] + [month_w]*len(forecast_periods) + [summary_w]*3

    headers = (
        ["EUR '000"]
        + [month_names.get(p.split("-")[1], p) for p in forecast_periods]
        + ["YTD", "YTG", "FY"]
    )
    header_row = [Paragraph("<b>{}</b>".format(h), S_TBL_HDR) for h in headers]
    rows = [header_row]

    def num_cells(row_obj, ytd_val, ytg_val, fy_val):
        cells = [Paragraph("{:,.0f}".format(row_obj[p]/1000), S_TBL_NUM)
                 for p in forecast_periods]
        cells.append(Paragraph("{:,.0f}".format(ytd_val/1000), S_TBL_NUM))
        cells.append(Paragraph("{:,.0f}".format(ytg_val/1000), S_TBL_NUM))
        cells.append(Paragraph("{:,.0f}".format(fy_val/1000),  S_TBL_NUM))
        return cells

    rows.append([Paragraph("<b>Revenue</b>", S_TBL)]
                + num_cells(rev_row, ytd_rev, ytg_rev, fy_rev))
    rows.append([Paragraph("Gross Profit", S_TBL)]
                + num_cells(gp_row, ytd_gp, ytg_gp, fy_gp))
    rows.append([Paragraph("<b>EBIT</b>", S_TBL)]
                + num_cells(ebit_row, ytd_ebit, ytg_ebit, fy_ebit))

    # EBIT margin row (percentages)
    margin_cells = [Paragraph("EBIT margin", S_TBL)]
    for p in forecast_periods:
        r = rev_row[p]
        e = ebit_row[p]
        margin_cells.append(Paragraph("{:.1%}".format(e/r if r else 0), S_TBL_NUM))
    margin_cells.append(Paragraph("{:.1%}".format(ytd_ebit/ytd_rev if ytd_rev else 0), S_TBL_NUM))
    margin_cells.append(Paragraph("{:.1%}".format(ytg_ebit/ytg_rev if ytg_rev else 0), S_TBL_NUM))
    margin_cells.append(Paragraph("{:.1%}".format(fy_ebit/fy_rev   if fy_rev  else 0), S_TBL_NUM))
    rows.append(margin_cells)

    style = [
        ("BACKGROUND",    (0,0), (-1,0),  TBL_HEADER),
        ("LINEBELOW",     (0,0), (-1,0),  1,   MID_BLUE),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 4),
        ("RIGHTPADDING",  (0,0), (-1,-1), 4),
        ("LINEBELOW",     (0,1), (-1,-1), 0.5, RULE_COLOR),
        # Shade the three summary columns and rule them off from the months
        ("BACKGROUND",    (-3,1), (-1,-1), ROW_ALT),
        ("LINEBEFORE",    (-3,0), (-3,-1), 0.5, RULE_COLOR),
        # Emphasise the FY column with a slightly stronger left rule
        ("LINEBEFORE",    (-1,0), (-1,-1), 0.75, MID_BLUE),
    ]
    t = Table(rows, colWidths=cw)
    t.setStyle(TableStyle(style))
    return t


_PNL_LINES = [
    ("Revenue",                  REVENUE_ITEMS_LOCAL, False, False),
    ("COGS",                     COGS_ITEMS_LOCAL,    True,  False),
    ("Gross Profit",             None,                False, True),
    ("Personnel Cost",           ["Personnel Cost"],  True,  False),
    ("Marketing Spend",          ["Marketing Spend"], True,  False),
    ("IT Infrastructure",        ["IT Infrastructure"], True, False),
    ("R&D Expense",              ["R&D Expense"],     True,  False),
    ("Total OpEx",               OPEX_ITEMS_LOCAL,    True,  True),
    ("Operating Profit (EBIT)",  None,                False, True),
]

_EXPENSE_NAMES = {"COGS", "Personnel Cost", "Marketing Spend",
                  "IT Infrastructure", "R&D Expense", "Total OpEx"}


def _pnl_summary_styles(pnl_lines, extra=None):
    """Reusable table-style commands for P&L summary/subtotal lines."""
    cmds = list(extra or [])
    for i, (name, _, _, _) in enumerate(pnl_lines, start=1):
        if name == "Gross Profit":
            cmds.append(("LINEABOVE", (0, i), (-1, i), 1, DARK_BLUE))
        elif name == "Total OpEx":
            cmds.append(("LINEABOVE", (0, i), (-1, i), 1, DARK_BLUE))
        elif name == "Operating Profit (EBIT)":
            cmds.append(("LINEABOVE", (0, i), (-1, i), 1.5, DARK_BLUE))
            cmds.append(("LINEBELOW", (0, i), (-1, i), 1.5, DARK_BLUE))
            cmds.append(("BACKGROUND", (0, i), (-1, i), LIGHT_BLUE))
    return cmds


def _quarterly_pnl_table(full_df, last_actual, forecast_periods):
    """P&L by quarter for the forecast year, with (A)ctual / (F)orecast tags."""
    fcst_year = forecast_periods[0][:4]
    quarters = [
        ("Q1", ["{}-01".format(fcst_year), "{}-02".format(fcst_year),
                "{}-03".format(fcst_year)]),
        ("Q2", ["{}-04".format(fcst_year), "{}-05".format(fcst_year),
                "{}-06".format(fcst_year)]),
        ("Q3", ["{}-07".format(fcst_year), "{}-08".format(fcst_year),
                "{}-09".format(fcst_year)]),
        ("Q4", ["{}-10".format(fcst_year), "{}-11".format(fcst_year),
                "{}-12".format(fcst_year)]),
    ]

    all_periods = set(full_df["period"].unique())

    def _qsum(items, periods):
        ps = [p for p in periods if p in all_periods]
        if not ps:
            return 0.0
        return float(full_df[
            full_df["line_item"].isin(items) &
            full_df["period"].isin(ps)
        ]["value"].sum())

    q_kind = {}
    for q_name, q_periods in quarters:
        present = [p for p in q_periods if p in all_periods]
        if not present or max(present) > last_actual:
            q_kind[q_name] = "F"
        else:
            q_kind[q_name] = "A"

    q_vals = {}
    for q_name, q_periods in quarters:
        present = [p for p in q_periods if p in all_periods]
        rev = _qsum(REVENUE_ITEMS_LOCAL, present)
        cogs = _qsum(COGS_ITEMS_LOCAL, present)
        gp = rev - cogs
        opex = _qsum(OPEX_ITEMS_LOCAL, present)
        ebit = gp - opex

        q_vals.setdefault("Revenue", {})[q_name] = rev
        q_vals.setdefault("COGS", {})[q_name] = cogs
        q_vals.setdefault("Gross Profit", {})[q_name] = gp
        for item in OPEX_ITEMS_LOCAL:
            q_vals.setdefault(item, {})[q_name] = _qsum([item], present)
        q_vals.setdefault("Total OpEx", {})[q_name] = opex
        q_vals.setdefault("Operating Profit (EBIT)", {})[q_name] = ebit

    q_names = [q[0] for q in quarters]
    col_hdrs = ["{} ({})".format(q, q_kind[q]) for q in q_names]
    col_hdrs.append("FY {}".format(fcst_year))

    label_col = 3.4 * cm
    data_col = (PAGE_W - label_col) / 5
    cw = [label_col] + [data_col] * 5

    header_row = [Paragraph("<b>EUR '000</b>", S_TBL_HDR)]
    header_row += [Paragraph("<b>{}</b>".format(h), S_TBL_HDR) for h in col_hdrs]
    rows = [header_row]

    for line_name, items, is_expense, is_summary in _PNL_LINES:
        vals = q_vals.get(line_name, {})
        fy = sum(vals.get(q, 0) for q in q_names)

        label = "<b>{}</b>".format(line_name) if is_summary else line_name
        row = [Paragraph(label, S_TBL)]

        for q in q_names:
            v = vals.get(q, 0) / 1000
            if is_expense:
                text = "({:,.0f})".format(abs(v))
            else:
                text = "{:,.0f}".format(v)
            row.append(Paragraph(text, S_TBL_NUM))

        fy_v = fy / 1000
        text = "({:,.0f})".format(abs(fy_v)) if is_expense else "{:,.0f}".format(fy_v)
        row.append(Paragraph(text, S_TBL_NUM))
        rows.append(row)

    margin_row = [Paragraph("EBIT margin", S_TBL)]
    rev_q = q_vals.get("Revenue", {})
    ebit_q = q_vals.get("Operating Profit (EBIT)", {})
    for q in q_names:
        r, e = rev_q.get(q, 0), ebit_q.get(q, 0)
        margin_row.append(Paragraph("{:.1%}".format(e / r if r else 0), S_TBL_NUM))
    fy_r = sum(rev_q.get(q, 0) for q in q_names)
    fy_e = sum(ebit_q.get(q, 0) for q in q_names)
    margin_row.append(Paragraph("{:.1%}".format(fy_e / fy_r if fy_r else 0), S_TBL_NUM))
    rows.append(margin_row)

    base_style = [
        ("BACKGROUND",    (0, 0), (-1, 0), TBL_HEADER),
        ("LINEBELOW",     (0, 0), (-1, 0), 1, MID_BLUE),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("LINEBELOW",     (0, 1), (-1, -1), 0.5, RULE_COLOR),
        ("LINEBEFORE",    (-1, 0), (-1, -1), 0.75, MID_BLUE),
        ("BACKGROUND",    (-1, 1), (-1, -1), ROW_ALT),
    ]
    style_cmds = _pnl_summary_styles(_PNL_LINES, extra=base_style)

    t = Table(rows, colWidths=cw)
    t.setStyle(TableStyle(style_cmds))
    return t


def _monthly_pnl_table(full_df, last_actual, forecast_periods):
    """Full P&L by month for the forecast year (Jan to Dec), all line items."""
    fcst_year = forecast_periods[0][:4]
    month_nums = ["{:02d}".format(m) for m in range(1, 13)]
    year_periods = ["{}-{}".format(fcst_year, mn) for mn in month_nums]
    all_periods = set(full_df["period"].unique())

    mn_short = {"01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
                "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
                "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec"}

    def _msum(items, period):
        if period not in all_periods:
            return None
        return float(full_df[
            full_df["line_item"].isin(items) &
            (full_df["period"] == period)
        ]["value"].sum())

    label_col = 2.6 * cm
    fy_col = 1.4 * cm
    month_col = (PAGE_W - label_col - fy_col) / 12
    cw = [label_col] + [month_col] * 12 + [fy_col]

    col_hdrs = []
    for mn in month_nums:
        p = "{}-{}".format(fcst_year, mn)
        kind = "(F)" if p > last_actual else "(A)"
        col_hdrs.append("{} {}".format(mn_short[mn], kind))
    col_hdrs.append("FY")

    header_row = [Paragraph("<b>EUR '000</b>", S_TBL_SM_HDR)]
    header_row += [Paragraph("<b>{}</b>".format(h), S_TBL_SM_HDR)
                   for h in col_hdrs]
    rows = [header_row]

    for line_name, items, is_expense, is_summary in _PNL_LINES:
        if items is None:
            if line_name == "Gross Profit":
                dep = (REVENUE_ITEMS_LOCAL, COGS_ITEMS_LOCAL, None)
            else:
                dep = (REVENUE_ITEMS_LOCAL, COGS_ITEMS_LOCAL, OPEX_ITEMS_LOCAL)
        else:
            dep = None

        label = "<b>{}</b>".format(line_name) if is_summary else line_name
        row = [Paragraph(label, S_TBL_SM)]
        fy = 0.0

        for mn in month_nums:
            p = "{}-{}".format(fcst_year, mn)
            if dep is not None:
                rev = _msum(dep[0], p)
                cogs = _msum(dep[1], p)
                if rev is None:
                    row.append(Paragraph(EM, S_TBL_SM_NUM))
                    continue
                val = rev - cogs
                if dep[2] is not None:
                    val -= (_msum(dep[2], p) or 0)
            else:
                val = _msum(items, p)
                if val is None:
                    row.append(Paragraph(EM, S_TBL_SM_NUM))
                    continue

            fy += val
            v = val / 1000
            text = "({:,.0f})".format(abs(v)) if is_expense else "{:,.0f}".format(v)
            row.append(Paragraph(text, S_TBL_SM_NUM))

        fy_v = fy / 1000
        text = "({:,.0f})".format(abs(fy_v)) if is_expense else "{:,.0f}".format(fy_v)
        row.append(Paragraph(text, S_TBL_SM_NUM))
        rows.append(row)

    margin_row = [Paragraph("EBIT margin", S_TBL_SM)]
    fy_rev_total = 0.0
    fy_ebit_total = 0.0
    for mn in month_nums:
        p = "{}-{}".format(fcst_year, mn)
        rev = _msum(REVENUE_ITEMS_LOCAL, p)
        if rev is None:
            margin_row.append(Paragraph(EM, S_TBL_SM_NUM))
            continue
        cogs = _msum(COGS_ITEMS_LOCAL, p) or 0
        opex = _msum(OPEX_ITEMS_LOCAL, p) or 0
        ebit = rev - cogs - opex
        fy_rev_total += rev
        fy_ebit_total += ebit
        margin_row.append(Paragraph(
            "{:.1%}".format(ebit / rev if rev else 0), S_TBL_SM_NUM))
    margin_row.append(Paragraph(
        "{:.1%}".format(fy_ebit_total / fy_rev_total if fy_rev_total else 0),
        S_TBL_SM_NUM))
    rows.append(margin_row)

    base_style = [
        ("BACKGROUND",    (0, 0), (-1, 0), TBL_HEADER),
        ("LINEBELOW",     (0, 0), (-1, 0), 1, MID_BLUE),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
        ("LINEBELOW",     (0, 1), (-1, -1), 0.5, RULE_COLOR),
        ("LINEBEFORE",    (-1, 0), (-1, -1), 0.75, MID_BLUE),
        ("BACKGROUND",    (-1, 1), (-1, -1), ROW_ALT),
    ]
    style_cmds = _pnl_summary_styles(_PNL_LINES, extra=base_style)

    t = Table(rows, colWidths=cw)
    t.setStyle(TableStyle(style_cmds))
    return t


def build_pdf_bytes(full_df, pnl_df, drivers_df, flags,
                    last_actual, forecast_periods,
                    commentary=None, tok_in=0, tok_out=0,
                    headcount_df=None, customer_df=None):
    """Build the forecast PDF and return its bytes.

    Shared builder used by both the CLI (write_pdf) and the web app.
    When commentary is None the overview, driver commentary, and key-risks
    sections are omitted, but the report is still valid: P&L, assumptions,
    chart, audit metadata, and flags.
    """
    import io

    ts = datetime.now(timezone.utc).isoformat()
    has_commentary = commentary is not None

    if has_commentary:
        sections = parse_forecast_sections(commentary)
    else:
        sections = {
            "forecast_overview": "", "driver_commentary": "",
            "key_risks": "", "data_flags": "",
        }

    story = []

    # 1. Cover
    story.append(_cover_block(
        DEFAULT_ENTITY, last_actual, forecast_periods,
        ts, tok_in, tok_out, len(flags), has_commentary=has_commentary,
    ))
    story.append(Spacer(1, 0.4 * cm))

    # 2. Forecast Overview (only with commentary)
    if has_commentary:
        story.append(_section_header("FORECAST OVERVIEW"))
        story.append(Spacer(1, 0.2 * cm))
        if sections["forecast_overview"]:
            story.append(Paragraph(
                sections["forecast_overview"].replace("\n", " "), S_BODY
            ))
        else:
            story.append(Paragraph("No overview available.", S_META))
        story.append(Spacer(1, 0.35 * cm))

    # 3. Forecast at a glance — chart + quarterly summary
    story.append(_section_header("FORECAST AT A GLANCE"))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_kpi_chart(full_df, last_actual, forecast_periods,
                            pnl_df, PAGE_W, 200))
    story.append(Spacer(1, 0.25 * cm))
    story.append(_quarterly_pnl_table(full_df, last_actual, forecast_periods))
    story.append(Spacer(1, 0.15 * cm))
    fcst_year = forecast_periods[0][:4]
    story.append(Paragraph(
        "Figures in EUR thousands. (A) = actuals, (F) = forecast. "
        "FY {} = full calendar year.".format(fcst_year),
        S_META
    ))
    story.append(Spacer(1, 0.35 * cm))

    # 4. Detailed monthly P&L
    story.append(_section_header("DETAILED P&L {} MONTHLY".format(EM)))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_monthly_pnl_table(full_df, last_actual, forecast_periods))
    story.append(Spacer(1, 0.15 * cm))
    story.append(Paragraph(
        "Figures in EUR thousands. Expense lines shown in brackets. "
        "Months marked (A) are booked actuals; (F) are model forecast.",
        S_META
    ))
    story.append(Spacer(1, 0.35 * cm))

    # 5. Forecast summary — compact KPI table
    story.append(_section_header("FORECAST SUMMARY"))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_compact_kpi_table(pnl_df, full_df, forecast_periods))
    story.append(Spacer(1, 0.15 * cm))
    story.append(Paragraph(
        "YTD = actuals booked so far this year. "
        "YTG = forecast remaining. FY = full year (YTD plus YTG).",
        S_META
    ))
    story.append(Spacer(1, 0.35 * cm))

    # 6. Driver Assumptions
    story.append(_section_header("DRIVER ASSUMPTIONS"))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_driver_table(drivers_df))
    story.append(Spacer(1, 0.35 * cm))

    # 6b. Operational Inputs (headcount + customer targets)
    if headcount_df is not None or customer_df is not None:
        story.append(_section_header("OPERATIONAL INPUTS"))
        story.append(Spacer(1, 0.2 * cm))
        if headcount_df is not None:
            story.append(Paragraph(
                "<b>Headcount schedule</b> (drives Personnel Cost)",
                S_TBL))
            story.append(Spacer(1, 0.1 * cm))
            story.append(_headcount_schedule_table(headcount_df))
            story.append(Spacer(1, 0.25 * cm))
        if customer_df is not None:
            story.append(Paragraph(
                "<b>Customer acquisition targets</b> (drives Marketing Spend)",
                S_TBL))
            story.append(Spacer(1, 0.1 * cm))
            story.append(_customer_targets_table(customer_df))
            story.append(Spacer(1, 0.15 * cm))
        story.append(Paragraph(
            "Personnel Cost = (starting headcount + cumulative net hires) "
            "x cost per head / 12. "
            "Marketing Spend = (new customers x CAC) + fixed campaign budget.",
            S_META))
        story.append(Spacer(1, 0.35 * cm))

    # 7. Driver Commentary (only with commentary)
    if has_commentary and sections["driver_commentary"]:
        story.append(_section_header("DRIVER COMMENTARY"))
        story.append(Spacer(1, 0.2 * cm))
        for line in sections["driver_commentary"].split("\n"):
            line = line.strip()
            if not line or line.startswith("---"):
                continue
            story.append(Paragraph(line, S_BODY))
            story.append(Spacer(1, 0.15 * cm))
        story.append(Spacer(1, 0.35 * cm))

    # 8. Key Risks (only with commentary)
    if has_commentary:
        story.append(_section_header("KEY RISKS AND RECOMMENDATIONS"))
        story.append(Spacer(1, 0.2 * cm))
        if sections["key_risks"]:
            for line in sections["key_risks"].split("\n"):
                line = line.strip().lstrip("-").strip()
                if not line:
                    continue
                story.append(Paragraph("&#8226; " + line, S_BODY))
                story.append(Spacer(1, 0.15 * cm))
        else:
            story.append(Paragraph("No specific risks flagged.", S_META))
        story.append(Spacer(1, 0.35 * cm))

    # 9. Data Flags
    story.append(_section_header("DATA FLAGS"))
    story.append(Spacer(1, 0.2 * cm))
    if flags:
        for flag in flags:
            story.append(_flag_box(flag, "error"))
    else:
        story.append(Paragraph("No flags raised.", S_BODY))
    story.append(Spacer(1, 0.4 * cm))

    # Footer
    story.append(HRFlowable(width="100%", thickness=0.5, color=RULE_COLOR))
    story.append(Spacer(1, 0.15 * cm))
    review_note = ("Required, {} flag(s)".format(len(flags)) if flags
                   else "Not required")
    story.append(Paragraph(
        "AI Driver-Based Rolling Forecast Pipeline  ·  {}  ·  {}  ·  "
        "Human review: {}".format(MODEL, ts[:10], review_note),
        S_META
    ))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=2 * cm, leftMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title="Rolling Forecast - {} to {}".format(
            forecast_periods[0], forecast_periods[-1]),
        author="AI Driver-Based Rolling Forecast Pipeline",
    )
    doc.build(story)
    return buf.getvalue()


def build_csv_bytes(pnl_df):
    """Return the P&L DataFrame as CSV bytes.

    Shared builder used by both the CLI (export_pnl_csv) and the web app,
    so the CSV columns match exactly.
    """
    return pnl_df.to_csv(index=False).encode("utf-8")


def write_pdf(commentary, full_df, pnl_df, drivers_df, flags, tok_in, tok_out,
              last_actual, forecast_periods):
    """Write the forecast PDF to disk (CLI entry point).

    Delegates to build_pdf_bytes for the shared story, then writes the
    file and updates the audit log.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts_file  = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    pdf_path = OUTPUT_DIR / "forecast_commentary_{}.pdf".format(ts_file)

    pdf_bytes = build_pdf_bytes(
        full_df, pnl_df, drivers_df, flags,
        last_actual, forecast_periods,
        commentary=commentary, tok_in=tok_in, tok_out=tok_out,
    )
    pdf_path.write_bytes(pdf_bytes)
    update_audit_pdf(pdf_path)

    print("[OK] PDF written")
    print("     PDF:  {}".format(pdf_path))
    print("     Size: {:.1f} KB".format(pdf_path.stat().st_size / 1024))
    return pdf_path


def export_pnl_csv(pnl_df, full_df, forecast_periods):
    """Export the P&L to a timestamped CSV on disk (CLI entry point).

    Delegates to build_csv_bytes for the shared content.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts_file  = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    csv_path = OUTPUT_DIR / "forecast_pnl_{}.csv".format(ts_file)

    csv_path.write_bytes(build_csv_bytes(pnl_df))
    update_audit_csv(csv_path)

    print("[OK] P&L CSV exported")
    print("     CSV:  {}".format(csv_path))
    return csv_path
