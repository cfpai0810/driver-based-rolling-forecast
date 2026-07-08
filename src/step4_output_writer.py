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

EM = "—"   # em dash


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


def _cover_block(entity, last_actual, forecast_periods, ts, tok_in, tok_out, nflags):
    """Full-width dark blue cover block."""
    rows = [
        [Paragraph(
            '<font color="white"><b>ROLLING FORECAST — {} TO {}</b></font>'.format(
                forecast_periods[0], forecast_periods[-1]),
            ParagraphStyle("CT", fontName="Helvetica-Bold", fontSize=16,
                textColor=colors.white, alignment=TA_CENTER)
        )],
        [Paragraph(
            '<font color="#AACCEE">{}  ·  Last actual: {}  ·  AI Generated  ·  {}</font>'.format(
                entity, last_actual, MODEL),
            ParagraphStyle("CS", fontName="Helvetica", fontSize=9,
                textColor=colors.HexColor("#AACCEE"), alignment=TA_CENTER)
        )],
        [Paragraph(
            '<font color="#6699BB">Generated {}  ·  {:,}/{:,} tokens  ·  {} flag(s)</font>'.format(
                ts[:10], tok_in, tok_out, nflags),
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


def _kpi_chart(forecast_periods, pnl_df, width, height):
    """
    Dual-axis chart: Revenue as bars (left axis), EBIT as line (right axis).
    Revenue is roughly 9x larger than EBIT, so separate axes keep both
    readable. The EBIT line makes the seasonal profit shape visible.
    """
    d = Drawing(width, height)

    months  = [p.split("-")[1] for p in forecast_periods]
    rev_row  = pnl_df[pnl_df["line"] == "Revenue"].iloc[0]
    ebit_row = pnl_df[pnl_df["line"] == "Operating Profit (EBIT)"].iloc[0]
    revenue = [float(rev_row[p])  for p in forecast_periods]
    ebit    = [float(ebit_row[p]) for p in forecast_periods]

    ml, mr, mt, mb = 55, 55, 30, 35
    plot_w = width - ml - mr
    plot_h = height - mt - mb
    n = len(forecast_periods)

    rev_max  = max(revenue) * 1.15 if revenue else 1
    ebit_max = max(ebit) * 1.25 if max(ebit) > 0 else 1

    month_names = {"01":"Jan","02":"Feb","03":"Mar","04":"Apr","05":"May","06":"Jun",
                   "07":"Jul","08":"Aug","09":"Sep","10":"Oct","11":"Nov","12":"Dec"}

    d.add(String(width/2, height-16, "Revenue and EBIT by month",
        fontName="Helvetica-Bold", fontSize=10, fillColor=DARK_BLUE, textAnchor="middle"))

    slot  = plot_w / n
    bar_w = slot * 0.5
    for i, rev in enumerate(revenue):
        x  = ml + i*slot + (slot-bar_w)/2
        bh = (rev / rev_max) * plot_h
        d.add(Rect(x, mb, bar_w, bh, fillColor=LIGHT_BLUE,
            strokeColor=MID_BLUE, strokeWidth=0.75))

    pts = []
    for i, e in enumerate(ebit):
        x = ml + i*slot + slot/2
        y = mb + (e / ebit_max) * plot_h
        pts.extend([x, y])
    if len(pts) >= 4:
        d.add(PolyLine(pts, strokeColor=GREEN, strokeWidth=2))
    for i, e in enumerate(ebit):
        x = ml + i*slot + slot/2
        y = mb + (e / ebit_max) * plot_h
        d.add(Circle(x, y, 2.5, fillColor=GREEN, strokeColor=colors.white, strokeWidth=0.5))

    for i, p in enumerate(forecast_periods):
        x = ml + i*slot + slot/2
        d.add(String(x, mb-14, month_names.get(p.split("-")[1], p.split("-")[1]),
            fontName="Helvetica", fontSize=8, fillColor=BODY_DARK, textAnchor="middle"))

    d.add(String(ml-8, height-mt+2, "Revenue", fontName="Helvetica", fontSize=7,
        fillColor=MID_BLUE, textAnchor="end"))
    d.add(String(ml-5, mb-2, "0", fontName="Helvetica", fontSize=7, fillColor=MUTED, textAnchor="end"))
    d.add(String(ml-5, mb+plot_h-4, "{:.1f}M".format(rev_max/1e6),
        fontName="Helvetica", fontSize=7, fillColor=MUTED, textAnchor="end"))

    d.add(String(width-mr+8, height-mt+2, "EBIT", fontName="Helvetica", fontSize=7,
        fillColor=GREEN, textAnchor="start"))
    d.add(String(width-mr+5, mb-2, "0", fontName="Helvetica", fontSize=7, fillColor=MUTED, textAnchor="start"))
    d.add(String(width-mr+5, mb+plot_h-4, "{:.0f}k".format(ebit_max/1e3),
        fontName="Helvetica", fontSize=7, fillColor=MUTED, textAnchor="start"))

    d.add(Line(ml, mb, ml, mb+plot_h, strokeColor=RULE_COLOR, strokeWidth=0.5))
    d.add(Line(width-mr, mb, width-mr, mb+plot_h, strokeColor=RULE_COLOR, strokeWidth=0.5))
    d.add(Line(ml, mb, width-mr, mb, strokeColor=RULE_COLOR, strokeWidth=0.5))

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


def write_pdf(commentary, full_df, pnl_df, drivers_df, flags, tok_in, tok_out,
              last_actual, forecast_periods):
    """
    Format the rolling forecast commentary into a professional A4 PDF.

    Layout:
        1. Cover        — entity, last actual, forecast range, metadata
        2. Overview     — 3-sentence forward-looking summary
        3. Forecast table — period x line item pivot, forecast rows shaded
        4. Driver assumptions — compact table of every driver
        5. Key risks    — Claude's recommendations as bullet points
        6. Data flags   — same pattern as Project 1

    Args:
        commentary:       string returned by call_claude()
        full_df:          DataFrame with actual + forecast rows
        drivers_df:       DataFrame of driver assumptions
        flags:            list of validation flag strings
        tok_in, tok_out:  token counts
        last_actual:      string — last locked period
        forecast_periods: list of forecast period strings

    Returns:
        pdf_path: Path to the written PDF file
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    now     = datetime.now(timezone.utc)
    ts_file = now.strftime("%Y-%m-%d_%H-%M-%S")
    ts_log  = now.isoformat()
    pdf_path = OUTPUT_DIR / "forecast_commentary_{}.pdf".format(ts_file)

    sections   = parse_forecast_sections(commentary)
    line_items = full_df["line_item"].unique().tolist()
    if "Revenue" in line_items:
        line_items = ["Revenue"] + [li for li in line_items if li != "Revenue"]

    story = []

    # 1. Cover
    story.append(_cover_block(
        DEFAULT_ENTITY, last_actual, forecast_periods,
        ts_log, tok_in, tok_out, len(flags)
    ))
    story.append(Spacer(1, 0.4 * cm))

    # 2. Forecast Overview
    story.append(_section_header("FORECAST OVERVIEW"))
    story.append(Spacer(1, 0.2 * cm))
    if sections["forecast_overview"]:
        story.append(Paragraph(
            sections["forecast_overview"].replace("\n", " "), S_BODY
        ))
    else:
        story.append(Paragraph("No overview available.", S_META))
    story.append(Spacer(1, 0.35 * cm))

    # 3. Forecast at a glance — chart + compact KPI table
    story.append(_section_header("FORECAST AT A GLANCE"))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_kpi_chart(forecast_periods, pnl_df, PAGE_W, 180))
    story.append(Spacer(1, 0.25 * cm))
    story.append(_compact_kpi_table(pnl_df, full_df, forecast_periods))
    story.append(Spacer(1, 0.15 * cm))
    story.append(Paragraph(
        "Figures in EUR thousands. YTD = actuals booked Jan to Jun 2026. "
        "YTG = forecast Jul to Dec 2026. FY = full year 2026 (YTD plus YTG). "
        "Full detailed P&L in the CSV export.",
        S_META
    ))
    story.append(Spacer(1, 0.35 * cm))

    # 4. Driver Assumptions
    story.append(_section_header("DRIVER ASSUMPTIONS"))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_driver_table(drivers_df))
    story.append(Spacer(1, 0.35 * cm))

    # 5. Driver Commentary (from Claude, one paragraph per line item)
    if sections["driver_commentary"]:
        story.append(_section_header("DRIVER COMMENTARY"))
        story.append(Spacer(1, 0.2 * cm))
        for line in sections["driver_commentary"].split("\n"):
            line = line.strip()
            if not line or line.startswith("---"):
                continue
            story.append(Paragraph(line, S_BODY))
            story.append(Spacer(1, 0.15 * cm))
        story.append(Spacer(1, 0.35 * cm))

    # 6. Key Risks
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

    # 7. Data Flags
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
    story.append(Paragraph(
        "AI Driver-Based Rolling Forecast Pipeline  ·  {}  ·  {}  ·  "
        "Human review: {}".format(
            MODEL, ts_log[:10],
            "Required — {} flag(s)".format(len(flags)) if flags else "Not required"
        ),
        S_META
    ))

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Rolling Forecast - {} to {}".format(
            forecast_periods[0], forecast_periods[-1]),
        author="AI Driver-Based Rolling Forecast Pipeline",
    )
    doc.build(story)

    update_audit_pdf(pdf_path)

    print("[OK] PDF written")
    print("     PDF:  {}".format(pdf_path))
    print("     Size: {:.1f} KB".format(pdf_path.stat().st_size / 1024))

    return pdf_path


def export_pnl_csv(pnl_df, full_df, forecast_periods):
    """
    Export the full detailed P&L to CSV — all nine lines, every period,
    plus a total column. This is the complete detail that no longer
    clutters the PDF.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    now      = datetime.now(timezone.utc)
    ts_file  = now.strftime("%Y-%m-%d_%H-%M-%S")
    csv_path = OUTPUT_DIR / "forecast_pnl_{}.csv".format(ts_file)

    pnl_df.to_csv(csv_path, index=False)

    # Record the CSV path in the audit trail
    update_audit_csv(csv_path)

    print("[OK] P&L CSV exported")
    print("     CSV:  {}".format(csv_path))
    return csv_path
