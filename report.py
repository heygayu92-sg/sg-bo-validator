"""
report.py
=========

Generates the downloadable PDF validation report (Step 3), using reportlab.

The report is structured to serve as both:
  1. A self-assessment summary of whether the RORC is supported by the
     Register of Members and per-controller verification, and
  2. The written explanation that ACRA expects to accompany supporting
     documents during audit.

Public function:
  generate_report_pdf(company_name, uen, controllers, unexplained_holders) -> io.BytesIO
"""

import io
from datetime import date

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch

from logic import notice_status_flag, rom_match_flag


def _table_style(header=True):
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F0F7FF")]),
        ]
    else:
        style += [
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F0F7FF")),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ]
    return TableStyle(style)


def generate_report_pdf(company_name, uen, controllers, unexplained_holders):
    """
    controllers: list of controller dicts. Each is expected to have:
      - display_name, category, mechanism, other_mechanism_text,
        direct_or_indirect, rom_match (dict), notice_status (dict),
        verification: dict with keys like
          {"annual_notice": {...}, "identity_doc": {...},
           "chain": [...], "mismatch_explanation": str,
           "resolved": bool}

    unexplained_holders: list of dicts, each a Register of Members entry
      that is >=25% but not in the RORC, with an added "investigation"
      dict describing how it was resolved (nominee trace / exemption /
      oversight), e.g.:
        {"shareholder_name":..., "percentage_of_total":...,
         "investigation": {"is_nominee": bool, "nominator_name": str,
                            "resolution_text": str, "resolved": bool, ...}}

    Returns: io.BytesIO containing the PDF.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.75*inch, bottomMargin=0.75*inch,
                             leftMargin=0.75*inch, rightMargin=0.75*inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("T", parent=styles["Title"], fontSize=18, spaceAfter=4)
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=14, textColor=colors.HexColor("#1F4E79"), spaceBefore=14, spaceAfter=6)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, textColor=colors.HexColor("#2E75B6"), spaceBefore=10, spaceAfter=4)
    normal = styles["Normal"]
    small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    cite = ParagraphStyle("Cite", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#7F7F7F"), spaceAfter=8)

    story = []
    story.append(Paragraph("SG Beneficial Ownership Validation Report", title_style))
    story.append(Paragraph(f"{company_name}" + (f" (UEN: {uen})" if uen else ""), normal))
    story.append(Paragraph(f"Date of validation: {date.today().strftime('%d %B %Y')}", small))
    story.append(Spacer(1, 12))

    # Determine overall status
    all_resolved = True
    for c in controllers:
        v = c.get("verification", {})
        if not v.get("resolved", False):
            all_resolved = False
        if v.get("consistency_flags"):
            all_resolved = False
    for h in unexplained_holders:
        inv = h.get("investigation", {})
        if not inv.get("resolved", False):
            all_resolved = False

    overall = "PASS" if all_resolved else "PASS WITH GAPS"
    status_color = colors.green if all_resolved else colors.orange
    story.append(Paragraph(f"<b>Overall status: <font color='{status_color.hexval()}'>{overall}</font></b>", normal))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "This report summarises a self-assessment of whether the RORC entries for this "
        "company are supported by the Register of Members, per-controller annual "
        "notices, and supporting documents, based on Part 11A of the Companies Act 1967 "
        "and ACRA guidance (last checked June 2026). It is intended to accompany "
        "supporting documents submitted to ACRA and to serve as the written explanation "
        "of those documents.", normal))

    story.append(PageBreak())

    # ---- Registrable controllers ----
    story.append(Paragraph("1. Registrable Controllers", h1))
    for c in controllers:
        story.append(Paragraph(f"{c['display_name']} ({c['category'].replace('_', ' ').title()})", h2))

        mech = c.get("mechanism", "Not specified")
        if mech == "Other":
            mech = c.get("other_mechanism_text") or "Other (unspecified)"

        rom = c.get("rom_match", {})
        rom_sev, rom_label = rom_match_flag(rom, c.get("mechanism", ""))

        notice = c.get("notice_status", {})
        notice_sev, notice_label = notice_status_flag(notice.get("status"))

        rows = [
            ["Mechanism of control", mech],
            ["Direct / Indirect", c.get("direct_or_indirect", "Not specified")],
            ["Register of Members check", f"{rom_label}" + (f" ({rom['matched_name']})" if rom.get("matched_name") else "")],
            ["Annual notice status", notice_label],
        ]

        v = c.get("verification", {})
        if v.get("identity_doc"):
            d = v["identity_doc"]
            rows.append(["Identity / registration document", f"{d.get('document_subtype', 'Provided')} - subject: {d.get('full_name') or d.get('entity_name') or 'see details'}"])
        if v.get("consistency_flags"):
            for cf in v["consistency_flags"]:
                rows.append([f"⚠ Discrepancy: {cf['field_label']}", cf["message"]])
        if v.get("chain"):
            chain_desc = " -> ".join(
                f"{e.get('name', '?')} ({e.get('type', '?')})" for e in v["chain"]
            )
            rows.append(["Ownership chain (traced)", chain_desc])
            if v.get("chain_termination"):
                rows.append(["Chain termination", v["chain_termination"]])
        if v.get("mismatch_explanation"):
            rows.append(["Discrepancy explanation", v["mismatch_explanation"]])

        rows.append(["Verification status", "Resolved" if v.get("resolved") else "Outstanding"])

        t = Table(rows, colWidths=[1.8*inch, 4.7*inch])
        t.setStyle(_table_style(header=False))
        story.append(t)
        story.append(Spacer(1, 8))

    story.append(PageBreak())

    # ---- Unexplained >=25% holders ----
    story.append(Paragraph("2. Shareholders Above 25% Not in RORC", h1))
    if not unexplained_holders:
        story.append(Paragraph("No shareholders holding 25% or more were found outside the RORC.", normal))
    else:
        for h_ in unexplained_holders:
            story.append(Paragraph(f"{h_['shareholder_name']} ({h_['percentage_of_total']}%)", h2))
            inv = h_.get("investigation", {})
            rows = []
            if inv.get("is_nominee") is True:
                rows.append(["Nominee shareholder?", "Yes"])
                rows.append(["Nominator (per RONS / nominee document)", inv.get("nominator_name", "Not provided")])
                if inv.get("beneficial_owner_name"):
                    rows.append(["Identified beneficial owner", inv.get("beneficial_owner_name")])
                if inv.get("identity_doc"):
                    d = inv["identity_doc"]
                    rows.append(["Identity document", f"{d.get('document_subtype', 'Provided')} - subject: {d.get('full_name') or d.get('entity_name') or 'see details'}"])
                rows.append(["Note", "An annual notice should be sent to this person going forward, per s.386AIA."])
            elif inv.get("is_nominee") is False:
                rows.append(["Nominee shareholder?", "No"])
                rows.append(["Explanation", inv.get("resolution_text", "Not provided")])
                if inv.get("exemption"):
                    rows.append(["Exemption category claimed", inv["exemption"]["label"]])
                    rows.append(["Legal basis", inv["exemption"]["basis"]])
            else:
                rows.append(["Status", "Not yet investigated"])

            rows.append(["Verification status", "Resolved" if inv.get("resolved") else "Outstanding"])
            t = Table(rows, colWidths=[1.8*inch, 4.7*inch])
            t.setStyle(_table_style(header=False))
            story.append(t)
            story.append(Spacer(1, 8))

    story.append(PageBreak())

    # ---- Outstanding gaps ----
    story.append(Paragraph("3. Outstanding Gaps", h1))
    gaps = []
    for c in controllers:
        v = c.get("verification", {})
        if not v.get("resolved"):
            gaps.append(f"{c['display_name']}: verification not yet marked as resolved.")
        for cf in v.get("consistency_flags", []):
            gaps.append(f"{c['display_name']}: {cf['message']}")
    for h_ in unexplained_holders:
        inv = h_.get("investigation", {})
        if not inv.get("resolved"):
            gaps.append(f"{h_['shareholder_name']} ({h_['percentage_of_total']}%): investigation not yet marked as resolved.")

    if gaps:
        for g in gaps:
            story.append(Paragraph(f"- {g}", normal))
    else:
        story.append(Paragraph("No outstanding gaps identified based on the information and documents provided.", normal))

    story.append(Spacer(1, 14))

    # ---- Regulatory basis ----
    story.append(Paragraph("4. Regulatory Basis (Source Last Checked: June 2026)", h1))
    rules_table = [
        ["Rule", "Source"],
        ["Significant interest / control thresholds", "Companies Act 1967, Sixteenth Schedule"],
        ["Registrability / tracing requirement", "Companies Act 1967 s.386AC"],
        ["Fallback to directors with executive control / CEO", "Companies Act 1967 s.386AFA"],
        ["Annual notice requirement", "Companies Act 1967 s.386AIA, s.386AG"],
        ["Unconfirmed particulars may be filed with note", "Companies Act 1967 ss.386AF(9), 386AG"],
        ["Nominee holdings treated as held by nominator", "RORC Guidance v2.0 para 7.14"],
        ["RORC exemption categories", "Companies Act 1967 s.386AC(c), 14th/15th Schedule"],
    ]
    t = Table(rules_table, colWidths=[4.2*inch, 2.3*inch])
    t.setStyle(_table_style())
    story.append(t)

    story.append(Spacer(1, 14))

    # ---- Disclaimer ----
    story.append(Paragraph("5. Disclaimer", h1))
    story.append(Paragraph(
        "This report is a document sufficiency self-assessment generated by an "
        "AI-assisted tool based on encoded rules derived from the Companies Act 1967 "
        "and ACRA guidance as at June 2026. It does not constitute legal advice. The "
        "company should review this report with a qualified professional before "
        "submitting documents and explanations to ACRA.", normal))

    doc.build(story)
    buf.seek(0)
    return buf
