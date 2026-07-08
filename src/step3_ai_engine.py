# =============================================================================
# step3_ai_engine.py — Layer 4: AI Prompt Construction and API Call
# =============================================================================
# Responsibilities:
#   - build_prompt():  construct system + user prompts for Claude
#   - call_claude():   send prompts, handle errors, return commentary
#
# This layer knows about: prompting, Anthropic API, token management
# This layer does NOT know about: file loading, forecast calculation, output files
# =============================================================================

import anthropic

from config import (
    ANTHROPIC_API_KEY,
    MODEL,
    MAX_TOKENS,
    DEFAULT_ENTITY,
    FORECAST_HORIZON,
)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def build_prompt(full_df, pnl_df, driver_detail, drivers_df,
                 last_actual, forecast_periods, flags):
    """
    Build the system and user prompts for the rolling forecast commentary.

    The user prompt ships the rolled-up P&L plus the full driver detail
    (seasonality indices, headcount build, CAC breakdown) so Claude can
    narrate accurately and compare each assumption against the actual trend.
    """

    system_prompt = (
        "You are a senior FP&A analyst writing a rolling forecast commentary "
        "for the CFO of Valencia Operations.\n\n"
        "<role_context>\n"
        "You are reviewing a 6-month driver-based rolling forecast for H2 2026. "
        "Actuals through June 2026 are locked. The forecast for July to "
        "December 2026 has been calculated by the model. Every number comes "
        "from the model, not from you.\n"
        "</role_context>\n\n"
        "<the_model>\n"
        "- Revenue: an annual year-on-year growth target spread across months "
        "using seasonality derived from last year's monthly pattern, so it "
        "captures the summer dip and Q4 peak rather than flat growth.\n"
        "- COGS: a percentage of each month's revenue.\n"
        "- Personnel Cost: starting headcount plus planned hires minus attrition, "
        "times the fully-loaded cost per head.\n"
        "- Marketing Spend: target new customers times cost to acquire each, "
        "plus a fixed campaign budget.\n"
        "- IT Infrastructure: fixed monthly contract. R&D: month-on-month growth.\n"
        "</the_model>\n\n"
        "<constraints>\n"
        "- NEVER invent numbers. Only use figures from the data provided.\n"
        "- Write like a trusted advisor speaking to a CFO. Direct, no filler.\n"
        "- Be concise. Every sentence must carry new information. No preamble, "
        "no sign-offs, no restatements of the actuals.\n"
        "- For each driver, compare the assumption against the actual trend where "
        "the data allows. The revenue_seasonality block shows the trailing 12 "
        "month revenue and the annual target, so state whether the growth "
        "assumption is above or below the recent actual run rate. This "
        "comparison is where the useful insight sits.\n"
        "- Use only standard ASCII characters. Do NOT use arrows, em dashes, or "
        "en dashes. Use commas, full stops, or plain words like 'to' and 'becomes'.\n"
        "- All amounts in EUR.\n"
        "</constraints>\n\n"
        "<output_format>\n"
        "Produce output in exactly this structure:\n\n"
        "FORECAST OVERVIEW\n"
        "[3 to 4 sentences. Lead with the P&L, using the exact figures from the "
        "simplified_pnl block. Do not round or approximate them. State H2 "
        "revenue, gross profit and margin, operating profit and margin. Name the "
        "weakest month for operating profit and why. State the overall direction.]\n\n"
        "DRIVER COMMENTARY\n"
        "[One paragraph each for the three driver-based lines, 3 sentences "
        "maximum per paragraph, with a bold label:\n"
        "**Revenue:** the growth assumption versus the actual run rate, the "
        "seasonal shape, the risk.\n"
        "**Personnel Cost:** the headcount build, what it implies, the risk.\n"
        "**Marketing Spend:** the customer target and CAC logic, the risk.\n"
        "Then one final line beginning **Other costs:** covering COGS, IT, and "
        "R&D together in two sentences maximum.]\n\n"
        "KEY RISKS AND RECOMMENDATIONS\n"
        "[2 to 3 bullets. Bold the single most important phrase in each. The "
        "assumption to challenge most, the scenario that would most change the "
        "outlook, the metric to watch.]\n\n"
        "DATA FLAGS\n"
        "[List each flag. If none, write: No flags raised.]\n"
        "</output_format>"
    )

    # ── P&L block ─────────────────────────────────────────────────────────────
    pnl_lines = []
    for _, row in pnl_df.iterrows():
        cells = "  ".join("{:>12,.0f}".format(row[p]) for p in forecast_periods)
        pnl_lines.append(
            "  {:24s} {}  |  Total {:>14,.0f}".format(row["line"], cells, row["total"])
        )
    pnl_block = "\n".join(pnl_lines)

    # ── Revenue seasonality block ─────────────────────────────────────────────
    seasonality_block = "  Not applicable."
    if "Revenue" in driver_detail and "indices" in driver_detail["Revenue"]:
        d = driver_detail["Revenue"]
        idx_lines = [
            "    Month {}: {:.3f}".format(m, d["indices"][m])
            for m in sorted(d["indices"].keys())
        ]
        seasonality_block = (
            "  Trailing 12 months revenue: EUR {:,.0f}\n"
            "  Annual growth assumption:   {:.0%}\n"
            "  Annual target next 12M:     EUR {:,.0f}\n"
            "  Seasonal indices (from last full calendar year):\n"
            "{}"
        ).format(
            d["trailing_12m"], d["yoy_growth"], d["annual_target"],
            "\n".join(idx_lines)
        )

    # ── Headcount build block ─────────────────────────────────────────────────
    headcount_block = "  Not applicable."
    for li, detail in driver_detail.items():
        if isinstance(detail, dict) and "start_headcount" in detail:
            hc_lines = ["  Starting headcount: {}".format(detail["start_headcount"])]
            for period, s in detail["schedule"].items():
                hc_lines.append(
                    "    {}: {} start, +{} hires, -{} attrition, {} end".format(
                        period, s["start"], s["hires"], s["attrition"], s["end"]
                    )
                )
            headcount_block = "\n".join(hc_lines)

    # ── CAC breakdown block ───────────────────────────────────────────────────
    cac_block = "  Not applicable."
    for li, detail in driver_detail.items():
        if isinstance(detail, dict) and any(
            isinstance(v, dict) and "new_customers" in v for v in detail.values()
        ):
            cac_lines = []
            for period, s in detail.items():
                cac_lines.append(
                    "    {}: {} new customers x EUR {:,.0f} CAC + EUR {:,.0f} fixed".format(
                        period, s["new_customers"], s["cac"], s["fixed"]
                    )
                )
            cac_block = "\n".join(cac_lines)

    # ── Driver assumptions summary ────────────────────────────────────────────
    driver_lines = []
    for _, row in drivers_df.iterrows():
        note = row.get("note", "") if "note" in row.index else ""
        driver_lines.append(
            "  {:20s} | {:16s} | {}".format(row["line_item"], row["driver_type"], note)
        )
    driver_block = "\n".join(driver_lines)

    flags_block = (
        "\n".join("  - {}".format(f) for f in flags)
        if flags else "  No flags raised."
    )

    user_prompt = (
        "FORECAST CONTEXT\n"
        "Entity:          {entity}\n"
        "Last actual:     {last_actual}\n"
        "Forecast period: {fcst_start} to {fcst_end}\n\n"
        "<simplified_pnl>\n"
        "{pnl}\n"
        "</simplified_pnl>\n\n"
        "<revenue_seasonality>\n"
        "{seasonality}\n"
        "</revenue_seasonality>\n\n"
        "<headcount_build>\n"
        "{headcount}\n"
        "</headcount_build>\n\n"
        "<customer_acquisition>\n"
        "{cac}\n"
        "</customer_acquisition>\n\n"
        "<driver_assumptions>\n"
        "{drivers}\n"
        "</driver_assumptions>\n\n"
        "<data_flags>\n"
        "{flags}\n"
        "</data_flags>\n\n"
        "Using the simplified P&L and the driver detail above, produce the "
        "rolling forecast commentary in the exact output format specified."
    ).format(
        entity      = DEFAULT_ENTITY,
        last_actual = last_actual,
        fcst_start  = forecast_periods[0],
        fcst_end    = forecast_periods[-1],
        pnl         = pnl_block,
        seasonality = seasonality_block,
        headcount   = headcount_block,
        cac         = cac_block,
        drivers     = driver_block,
        flags       = flags_block,
    )

    print("\n[OK] Prompts built")
    print("     P&L lines:     {}".format(len(pnl_df)))
    print("     Driver detail: {} items".format(len(driver_detail)))
    print("     Flags:         {}".format(len(flags)))

    return system_prompt, user_prompt


def call_claude(system_prompt, user_prompt):
    """
    Send prompts to Claude and return commentary, token counts, and stop reason.
    """
    print("\n[..] Calling Claude API ({})...".format(MODEL))

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
    except anthropic.AuthenticationError:
        raise RuntimeError(
            "Authentication failed. Check ANTHROPIC_API_KEY in .env."
        )
    except anthropic.RateLimitError:
        raise RuntimeError(
            "Rate limit reached. Wait 60 seconds and try again."
        )
    except anthropic.APIStatusError as e:
        raise RuntimeError(
            "API error {}: {}".format(e.status_code, e.message)
        )
    except anthropic.APIConnectionError:
        raise RuntimeError(
            "Cannot connect to Anthropic API. Check internet connection."
        )

    if not response.content:
        raise RuntimeError("Claude returned an empty response.")

    response_text = response.content[0].text
    input_tokens  = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    stop_reason   = response.stop_reason

    if stop_reason == "max_tokens":
        print("[WARN] Response truncated. Consider increasing MAX_TOKENS.")

    if output_tokens < 200 and stop_reason != "max_tokens":
        print("[WARN] Unusually low output ({} tokens). Review output.".format(
            output_tokens))

    approx_cost = (input_tokens * 0.000003) + (output_tokens * 0.000015)

    print("[OK] Claude responded")
    print("     Stop reason:   {}".format(stop_reason))
    print("     Input tokens:  {:,}".format(input_tokens))
    print("     Output tokens: {:,}".format(output_tokens))
    print("     Approx cost:   EUR {:.4f}".format(approx_cost))
    print("\n{}".format("=" * 60))
    print("ROLLING FORECAST COMMENTARY — {}".format(DEFAULT_ENTITY))
    print("{}".format("=" * 60))
    print(response_text)
    print("{}".format("=" * 60))

    return response_text, input_tokens, output_tokens, stop_reason
