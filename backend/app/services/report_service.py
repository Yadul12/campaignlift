"""
Executive Campaign Report & Decision Support Export Service.

Generates structured executive reports (JSON preview, formatted PDF via ReportLab,
and multi-sheet Excel via OpenPyXL) using the EXACT same computed metrics as the
CampaignLift dashboard services — zero duplicated or divergent math.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import settings
from app.schemas.analytics import GlobalFilterParams
from app.services.economics_service import get_promotion_economics
from app.services.experiment_service import get_experiment_detail
from app.services.funnel_service import get_campaign_funnel


def _fmt_curr(val: float | None) -> str:
    if val is None:
        return "N/A (Non-Causal)"
    sign = "-" if val < 0 else ""
    return f"{sign}${abs(val):,.2f}"


def _fmt_pct(val: float | None) -> str:
    if val is None:
        return "N/A"
    return f"{val * 100:.2f}%"


def _fmt_p(val: float | None) -> str:
    if val is None:
        return "N/A"
    return "< 0.0001" if val < 0.0001 else f"{val:.4f}"


def build_executive_report(campaign_id: int) -> dict[str, Any] | None:
    exp = get_experiment_detail(campaign_id)
    if not exp:
        return None

    filt = GlobalFilterParams(campaign_id=campaign_id)
    econ = get_promotion_economics(filt)
    funnel = get_campaign_funnel(filt)

    camp = exp["campaign"]
    diag = exp["diagnostics"]
    inc = exp["incremental_summary"]
    econ_sum = econ["summary"]
    econ_row = econ["campaigns"][0] if econ["campaigns"] else {}
    is_rct = diag["is_rct"]

    # Build structured narrative strictly grounded in computed values
    offer_desc = (
        f"{camp['discount_pct']:.1f}% fare discount" if camp["discount_pct"] > 0 else ""
    )
    if camp["bonus_miles_offer"] > 0:
        offer_desc = (f"{offer_desc} + " if offer_desc else "") + f"{camp['bonus_miles_offer']:,} bonus miles"
    if not offer_desc:
        offer_desc = "targeted promotional messaging"

    business_question = (
        f"Did Meridian Air's {camp['campaign_type']} campaign '{camp['campaign_name']}' ({camp['campaign_code']}, offering {offer_desc} "
        f"via {camp['channel_name']} to {camp['target_segment_name']} on {camp['target_route_code']}) generate genuinely incremental bookings "
        f"and positive net contribution margin, or did promotional incentives primarily subsidize organic demand?"
    )

    if is_rct:
        methodology = (
            f"Evaluated as a simulated Randomized Controlled Trial (RCT) on an Intention-to-Treat (ITT) basis across all "
            f"{diag['n_treatment']:,} treatment and {diag['n_control']:,} control customers assigned between {camp['start_date']} and {camp['end_date']} "
            f"(with a {camp['booking_window_days']}-day post-campaign booking window). Conversion lift was evaluated using a two-proportion z-test "
            f"and Pearson chi-square test; booking frequency, net revenue per customer, and contribution margin per customer were evaluated via "
            f"Welch's two-sample t-test. Sample Ratio Mismatch (SRM p = {_fmt_p(diag['srm_p_value'])}) and pre-period covariate balance "
            f"(max |SMD| = {diag['max_covariate_smd']:.3f}) verify randomization integrity. Note: {diag['exposure_compliance_rate']*100:.1f}% "
            f"of assigned treatment subjects were verified as reached/exposed; ITT preserves unbiasedness despite non-compliance."
        )
    else:
        methodology = (
            f"Evaluated as a non-randomized Observational campaign comparing {diag['n_treatment']:,} targeted customers against "
            f"{diag['n_control']:,} untargeted comparison customers. Pre-period covariate diagnostics reveal substantial selection bias "
            f"(max |SMD| = {diag['max_covariate_smd']:.3f} > 0.20), meaning targeted customers had higher baseline booking propensity prior to exposure. "
            f"Accordingly, naive differences are NOT reported as causal incremental lift; an Inverse Probability Weighting (IPW) sensitivity check "
            f"is supplied strictly as a directional bound subject to potential unobserved confounding."
        )

    conv_m = next(m for m in exp["metrics_table"] if m["metric_key"] == "conversion_rate")
    contrib_m = next(m for m in exp["metrics_table"] if m["metric_key"] == "contribution_per_customer")

    if is_rct:
        inc_impact_summary = (
            f"On an ITT basis, treatment conversion was {_fmt_pct(conv_m['treatment_value'])} vs. {_fmt_pct(conv_m['control_value'])} in control "
            f"(absolute lift {(conv_m['lift_abs'] or 0)*100:+.2f} pp, 95% CI [{(conv_m['ci_low'] or 0)*100:+.2f}, {(conv_m['ci_high'] or 0)*100:+.2f}] pp, "
            f"p = {_fmt_p(conv_m['p_value'])}). Scaling ITT booking frequency lift to {diag['n_treatment']:,} assigned treatment customers yields "
            f"{inc['incremental_bookings']:,.1f} incremental bookings (compared to {econ_row.get('attributed_bookings', 0):,} attributed bookings), "
            f"{_fmt_curr(inc['incremental_revenue'])} in incremental net revenue, and {_fmt_curr(inc['incremental_contribution'])} in net incremental contribution "
            f"after deducting {_fmt_curr(inc['marketing_spend'])} in media/execution costs."
        )
    else:
        ipw = diag.get("ipw_sensitivity") or {}
        inc_impact_summary = (
            f"Causal incremental lift is withheld due to non-randomized targeting (max |SMD| = {diag['max_covariate_smd']:.3f}). "
            f"Unadjusted targeted conversion was {_fmt_pct(conv_m['treatment_value'])} vs. {_fmt_pct(conv_m['control_value'])} in the comparison group. "
            f"After observable covariate IPW reweighting, the sensitivity conversion difference narrowed to "
            f"{(ipw.get('ipw_conversion_lift_abs') or 0)*100:+.2f} pp and contribution sensitivity to {_fmt_curr(ipw.get('ipw_contrib_lift_per_cust'))}/customer."
        )

    deadweight = econ_row.get("deadweight_subsidy")
    financial_summary = (
        f"Attributed bookings generated {_fmt_curr(econ_sum['gross_revenue'])} in gross booking revenue before {_fmt_curr(econ_sum['discount_cost'])} "
        f"in fare discounts, {_fmt_curr(econ_sum['variable_cost'])} in estimated variable operating costs, {_fmt_curr(econ_sum['bonus_miles_cost'])} "
        f"in promotional loyalty miles liability, and {_fmt_curr(econ_sum['other_promo_cost'])} in channel/media spend — leaving "
        f"{_fmt_curr(econ_sum['contribution_after_promo'])} in attributed contribution after promotion (margin erosion: {_fmt_pct(econ_sum['margin_erosion_pct'])})."
        + (f" Approximately {_fmt_curr(deadweight)} in promo discounts/miles went to baseline customers who would have booked organically." if deadweight is not None else "")
    )

    risks = [
        "All data and randomized experiments in CampaignLift are synthetic simulations built for commercial analytics demonstration.",
        f"Exposure compliance was {diag['exposure_compliance_rate']*100:.1f}%; deliverability losses dilute ITT effect size relative to treated-only impact.",
        "Average Booking Value (ABV) is conditional on booking and may reflect itinerary mix shifts rather than pure fare elasticity.",
        "Seat displacement / opportunity cost on high-load-factor peak flights is approximated via route variable costs and baseline load factors.",
    ]
    if not is_rct:
        risks.insert(0, "CRITICAL: Non-randomized observational campaign exhibits confirmed selection bias; causal claims are invalid without an RCT.")
    if is_rct and (inc["incremental_contribution"] or 0) < 0:
        risks.insert(0, "PROFITABILITY RISK: Campaign destroyed net contribution margin because fare discounts/media spend outweighed incremental demand.")

    rec_status = inc["recommendation_status"]
    rec_map = {
        "Scale Budget": f"SCALE BUDGET: Statistically credible positive incremental contribution ({_fmt_curr(inc['incremental_contribution'])}). Expand allocation in {camp['channel_name']} while maintaining a 15-20% persistent holdout to monitor saturation.",
        "Pause / Redesign": f"PAUSE & REDESIGN: Net incremental contribution is negative ({_fmt_curr(inc['incremental_contribution'])}). Halt broad rollout; replace steep cash discounts with targeted loyalty miles or suppress high-baseline 'Sure Things' customers.",
        "Reduce Discount / Optimize": f"REDUCE DISCOUNT DEPTH: Campaign lifted bookings ({(inc['incremental_bookings'] or 0.0):,.1f} incremental) but over-subsidized organic bookers, eroding net contribution ({_fmt_curr(inc['incremental_contribution'])}). Retest with a 40-50% smaller discount or tighter audience targeting.",
        "Run Controlled RCT": f"RUN CONTROLLED RCT BEFORE SCALING: Observational targeting bias (max |SMD| = {diag['max_covariate_smd']:.2f}) prevents causal verification. Design a 70/30 randomized holdout test sized via the Experimentation Lab Power Calculator.",
        "Inconclusive — Retest": f"INCONCLUSIVE — RETEST OR REALLOCATE: Statistical confidence was insufficient to confirm positive incremental contribution (conv p = {_fmt_p(conv_m['p_value'])}, contrib p = {_fmt_p(contrib_m['p_value'])}). Increase sample size or strengthen offer differentiation before scaling.",
        "Audit Randomization": "AUDIT RANDOMIZATION: Sample Ratio Mismatch detected; investigate assignment logging before making budget decisions.",
    }

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_label": settings.dataset_label,
        "campaign": camp,
        "business_question": business_question,
        "methodology": methodology,
        "diagnostics": diag,
        "metrics_table": exp["metrics_table"],
        "incremental_impact": {
            "summary": inc_impact_summary,
            **inc,
        },
        "financial_impact": {
            "summary": financial_summary,
            "summary_metrics": econ_sum,
            "campaign_ledger": econ_row,
            "waterfall": econ["waterfall"],
        },
        "funnel_stages": funnel["stages"],
        "subgroup_hte": exp["subgroup_hte"],
        "risks_and_limitations": risks,
        "recommended_action": {
            "status": rec_status,
            "narrative": rec_map.get(rec_status, rec_status),
        },
    }


def render_executive_report_pdf(campaign_id: int) -> bytes | None:
    report = build_executive_report(campaign_id)
    if not report:
        return None

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title=f"CampaignLift Executive Report — {report['campaign']['campaign_code']}",
    )

    styles = getSampleStyleSheet()
    navy = colors.HexColor("#0F2942")
    cobalt = colors.HexColor("#1E5B94")
    slate = colors.HexColor("#475569")
    border_grey = colors.HexColor("#CBD5E1")
    bg_light = colors.HexColor("#F8FAFC")

    h1 = ParagraphStyle("CLH1", parent=styles["Heading1"], fontSize=15, textColor=navy, spaceAfter=4, leading=18)
    sub = ParagraphStyle("CLSub", parent=styles["Normal"], fontSize=8.5, textColor=slate, spaceAfter=10)
    h2 = ParagraphStyle("CLH2", parent=styles["Heading2"], fontSize=11, textColor=navy, spaceBefore=10, spaceAfter=4, leading=14)
    body = ParagraphStyle("CLBody", parent=styles["Normal"], fontSize=8.8, textColor=colors.HexColor("#1E293B"), leading=12.5, spaceAfter=5)
    rec_style = ParagraphStyle("CLRec", parent=styles["Normal"], fontSize=9.2, textColor=navy, leading=13, backColor=colors.HexColor("#EFF6FF"), borderPadding=8)

    camp = report["campaign"]
    diag = report["diagnostics"]
    inc = report["incremental_impact"]
    fin = report["financial_impact"]["summary_metrics"]

    story: list[Any] = [
        Paragraph(f"CAMPAIGNLIFT · EXECUTIVE CAMPAIGN EVALUATION", sub),
        Paragraph(f"{camp['campaign_code']}: {camp['campaign_name']}", h1),
        Paragraph(
            f"<b>Study Design:</b> {camp['experiment_type']} &nbsp;|&nbsp; "
            f"<b>Type:</b> {camp['campaign_type']} &nbsp;|&nbsp; "
            f"<b>Channel:</b> {camp['channel_name']} &nbsp;|&nbsp; "
            f"<b>Window:</b> {camp['start_date']} to {camp['end_date']} (+{camp['booking_window_days']}d) &nbsp;|&nbsp; "
            f"<i>{report['dataset_label']}</i>",
            sub,
        ),
    ]

    # 1. Business Question
    story.append(Paragraph("1. Business Question", h2))
    story.append(Paragraph(report["business_question"], body))

    # 2. Campaign Overview & Key Metrics Table
    story.append(Paragraph("2. Campaign Overview & Commercial Summary", h2))
    ov_data = [
        ["Target Segment", camp["target_segment_name"], "Route Market", camp["target_route_code"]],
        ["Offer Structure", f"{camp['discount_pct']:.1f}% Off / {camp['bonus_miles_offer']:,} Miles", "Marketing Spend", _fmt_curr(inc["marketing_spend"])],
        ["Treatment / Targeted N", f"{diag['n_treatment']:,}", "Control / Comparison N", f"{diag['n_control']:,}"],
        ["Exposure Compliance", f"{diag['exposure_compliance_rate']*100:.1f}%", "SRM / Balance", f"SRM={'PASS' if diag['srm_passed'] else ('FAIL' if diag['is_rct'] else 'N/A')} | max|SMD|={diag['max_covariate_smd']:.3f}"],
    ]
    t_ov = Table(ov_data, colWidths=[1.45 * inch, 2.2 * inch, 1.45 * inch, 2.2 * inch])
    t_ov.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), bg_light),
        ("BACKGROUND", (2, 0), (2, -1), bg_light),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, border_grey),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t_ov)
    story.append(Spacer(1, 6))

    # 3. Methodology
    story.append(Paragraph("3. Methodology & Statistical Integrity", h2))
    story.append(Paragraph(report["methodology"], body))

    # 4. Control & Treatment Results
    story.append(Paragraph("4. Control vs. Treatment Results", h2))
    m_rows = [["Metric", "Control", "Treatment", "Abs Lift", "95% CI", "Test & p-value", "Power"]]
    for m in report["metrics_table"]:
        if m["unit"] == "percent":
            c_s, t_s = _fmt_pct(m["control_value"]), _fmt_pct(m["treatment_value"])
            l_s = f"{(m['lift_abs'] or 0)*100:+.2f} pp"
            ci_s = f"[{(m['ci_low'] or 0)*100:+.2f}, {(m['ci_high'] or 0)*100:+.2f}]" if m["ci_low"] is not None else "N/A"
        elif m["unit"] == "currency":
            c_s, t_s = _fmt_curr(m["control_value"]), _fmt_curr(m["treatment_value"])
            l_s = _fmt_curr(m["lift_abs"])
            ci_s = f"[{_fmt_curr(m['ci_low'])}, {_fmt_curr(m['ci_high'])}]" if m["ci_low"] is not None else "N/A"
        else:
            c_s = f"{(m['control_value'] or 0):.4f}"
            t_s = f"{(m['treatment_value'] or 0):.4f}"
            l_s = f"{(m['lift_abs'] or 0):+.4f}"
            ci_s = f"[{(m['ci_low'] or 0):+.4f}, {(m['ci_high'] or 0):+.4f}]" if m["ci_low"] is not None else "N/A"
        m_rows.append([
            m["metric_name"],
            c_s,
            t_s,
            l_s,
            ci_s,
            f"{m['test_stat_label']}={(m['test_stat'] or 0):.2f} (p={_fmt_p(m['p_value'])})",
            f"{(m['power'] or 0)*100:.0f}%",
        ])
    t_m = Table(m_rows, colWidths=[1.85 * inch, 0.78 * inch, 0.78 * inch, 0.78 * inch, 1.15 * inch, 1.41 * inch, 0.55 * inch])
    t_m.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.2),
        ("GRID", (0, 0), (-1, -1), 0.4, border_grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, bg_light]),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_m)
    story.append(Spacer(1, 6))

    # 5. Incremental Impact
    story.append(Paragraph("5. Incremental Impact", h2))
    story.append(Paragraph(report["incremental_impact"]["summary"], body))

    # 6. Financial Impact
    story.append(Paragraph("6. Financial Impact & Promotion Economics", h2))
    story.append(Paragraph(report["financial_impact"]["summary"], body))
    fin_rows = [
        ["Gross Revenue", "Fare Discounts", "Variable Costs", "Bonus Miles Cost", "Media Spend", "Contrib After Promo", "RCT Inc. Contrib"],
        [
            _fmt_curr(fin["gross_revenue"]),
            _fmt_curr(fin["discount_cost"]),
            _fmt_curr(fin["variable_cost"]),
            _fmt_curr(fin["bonus_miles_cost"]),
            _fmt_curr(fin["other_promo_cost"]),
            _fmt_curr(fin["contribution_after_promo"]),
            _fmt_curr(inc["incremental_contribution"]),
        ],
    ]
    t_f = Table(fin_rows, colWidths=[1.04 * inch] * 7)
    t_f.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), cobalt),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.4, border_grey),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_f)

    # 7. Statistical Confidence & Risks
    story.append(Paragraph("7. Statistical Confidence, Risks & Limitations", h2))
    for risk in report["risks_and_limitations"]:
        story.append(Paragraph(f"• {risk}", body))

    # 8. Recommended Action
    story.append(Paragraph("8. Recommended Commercial Action", h2))
    story.append(Paragraph(f"<b>{report['recommended_action']['narrative']}</b>", rec_style))

    doc.build(story)
    return buf.getvalue()


def render_executive_report_excel(campaign_id: int) -> bytes | None:
    report = build_executive_report(campaign_id)
    if not report:
        return None

    wb = Workbook()
    navy_fill = PatternFill(start_color="0F2942", end_color="0F2942", fill_type="solid")
    sub_fill = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
    white_bold = Font(color="FFFFFF", bold=True, size=10)
    bold_font = Font(bold=True, size=10, color="0F2942")

    # Sheet 1: Executive Summary
    ws1 = wb.active
    ws1.title = "Executive Summary"
    camp = report["campaign"]
    diag = report["diagnostics"]
    inc = report["incremental_impact"]

    rows_s1 = [
        ("CampaignLift Executive Campaign Report", report["dataset_label"]),
        ("Campaign Code", camp["campaign_code"]),
        ("Campaign Name", camp["campaign_name"]),
        ("Campaign Type", camp["campaign_type"]),
        ("Study Design", camp["experiment_type"]),
        ("Channel", camp["channel_name"]),
        ("Target Segment", camp["target_segment_name"]),
        ("Route Market", camp["target_route_code"]),
        ("Active Dates", f"{camp['start_date']} to {camp['end_date']} (+{camp['booking_window_days']}d booking window)"),
        ("Business Question", report["business_question"]),
        ("Methodology", report["methodology"]),
        ("Incremental Impact Summary", inc["summary"]),
        ("Financial Impact Summary", report["financial_impact"]["summary"]),
        ("Recommended Action Status", report["recommended_action"]["status"]),
        ("Recommended Action Detail", report["recommended_action"]["narrative"]),
        ("Generated At (UTC)", report["generated_at_utc"]),
    ]
    for idx, (k, v) in enumerate(rows_s1, start=1):
        ws1.append([k, v])
        ws1.cell(idx, 1).font = bold_font
        ws1.cell(idx, 1).fill = sub_fill
        ws1.cell(idx, 2).alignment = Alignment(wrap_text=True)
    ws1.column_dimensions["A"].width = 28
    ws1.column_dimensions["B"].width = 96

    # Sheet 2: Experiment Results
    ws2 = wb.create_sheet("Experiment Statistics")
    headers2 = ["Metric", "Control", "Treatment", "Absolute Lift", "Relative Lift", "95% CI Low", "95% CI High", "Test Statistic", "p-value", "Achieved Power", "Methodological Test"]
    ws2.append(headers2)
    for cell in ws2[1]:
        cell.fill = navy_fill
        cell.font = white_bold
    for m in report["metrics_table"]:
        ws2.append([
            m["metric_name"], m["control_value"], m["treatment_value"], m["lift_abs"], m["lift_rel"],
            m["ci_low"], m["ci_high"], m["test_stat"], m["p_value"], m["power"], m["primary_test"],
        ])
    for col_cells in ws2.columns:
        ws2.column_dimensions[col_cells[0].column_letter].width = 18
    ws2.column_dimensions["A"].width = 34
    ws2.column_dimensions["K"].width = 42

    # Sheet 3: Promotion Economics
    ws3 = wb.create_sheet("Promotion Economics")
    ws3.append(["Economic Line Item", "Amount (USD / Metric)"])
    for cell in ws3[1]:
        cell.fill = navy_fill
        cell.font = white_bold
    fin = report["financial_impact"]["summary_metrics"]
    ledger = report["financial_impact"]["campaign_ledger"]
    for label, val in [
        ("Gross Booking Revenue", fin["gross_revenue"]),
        ("Fare Discounts", -fin["discount_cost"]),
        ("Estimated Variable Operating Costs", -fin["variable_cost"]),
        ("Contribution Before Promotion", fin["contribution_before_promo"]),
        ("Bonus Loyalty Miles Liability Cost", -fin["bonus_miles_cost"]),
        ("Media & Other Promotional Cost", -fin["other_promo_cost"]),
        ("Contribution After Promotion (Attributed)", fin["contribution_after_promo"]),
        ("Margin Erosion %", fin["margin_erosion_pct"]),
        ("RCT Incremental Bookings", inc["incremental_bookings"]),
        ("RCT Incremental Revenue", inc["incremental_revenue"]),
        ("RCT Incremental Contribution", inc["incremental_contribution"]),
        ("Cost per Incremental Booking (iCPA)", inc["cost_per_incremental_booking"]),
        ("Estimated Deadweight Baseline Subsidy", ledger.get("deadweight_subsidy")),
    ]:
        ws3.append([label, val])
    ws3.column_dimensions["A"].width = 40
    ws3.column_dimensions["B"].width = 22

    # Sheet 4: Campaign Funnel
    ws4 = wb.create_sheet("Campaign Funnel")
    ws4.append(["Stage", "Customer Count", "Step Conversion Rate", "Drop-off Count", "Drop-off Rate", "Cumulative From Assigned"])
    for cell in ws4[1]:
        cell.fill = navy_fill
        cell.font = white_bold
    for st in report["funnel_stages"]:
        ws4.append([st["stage_label"], st["count"], st["step_conversion_rate"], st["dropoff_count"], st["dropoff_rate"], st["cumulative_from_assigned"]])
    for col_cells in ws4.columns:
        ws4.column_dimensions[col_cells[0].column_letter].width = 22

    # Sheet 5: Subgroup HTE & Covariate Balance
    ws5 = wb.create_sheet("Subgroup & Diagnostics")
    ws5.append(["Segment", "N Treatment", "N Control", "Control Conv", "Treatment Conv", "Conv Lift (pp)", "Conv p-value", "Contrib Lift/Cust ($)", "Contrib p-value"])
    for cell in ws5[1]:
        cell.fill = navy_fill
        cell.font = white_bold
    for h in report["subgroup_hte"]:
        ws5.append([
            h["segment_name"], h["n_treatment"], h["n_control"], h["control_conv"], h["treatment_conv"],
            h["conv_lift_pp"], h["conv_p_value"], h["contrib_lift_per_cust"], h["contrib_p_value"],
        ])
    ws5.append([])
    ws5.append(["Pre-Period Covariate", "Treatment Mean", "Control Mean", "SMD", "Status"])
    for cb in diag.get("covariate_balance", []):
        ws5.append([cb["covariate"], cb["treatment_mean"], cb["control_mean"], cb["smd"], cb["status"]])
    for col_cells in ws5.columns:
        ws5.column_dimensions[col_cells[0].column_letter].width = 20

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
