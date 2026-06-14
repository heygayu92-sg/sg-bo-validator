"""
SG BO Validator — Full Prototype (Stages 1-3)

A single-file Streamlit app for validating Singapore Beneficial Ownership
(RORC / ROND / RONS / Register of Members) filings, building an
evidence-based ownership chain, and generating a downloadable validation
report.

Stage 1 — Upload primary registers, AI parsing + confirmation, first-cut
          cross-check.
Stage 2 — For each candidate controller, ask clarifying questions, request
          supporting documents, parse + confirm, validate.
Stage 3 — Build the ownership chain (with exemption termination logic),
          show gap analysis, generate downloadable PDF report.

This is a prototype for demonstration purposes only. It is not legal
advice.
"""

import streamlit as st
import anthropic
import json
import base64
import os
import io
from datetime import date

from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch


# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(
    page_title="SG BO Validator",
    page_icon="🔎",
    layout="wide",
)

MODEL = "claude-sonnet-4-6"


# =============================================================================
# ANTHROPIC CLIENT
# =============================================================================
def get_client():
    api_key = st.secrets.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY"))
    if not api_key:
        st.error(
            "No Anthropic API key found. Add ANTHROPIC_API_KEY to your "
            "Streamlit secrets (see README)."
        )
        st.stop()
    return anthropic.Anthropic(api_key=api_key)


# =============================================================================
# EXTRACTION PROMPTS — STAGE 1 (PRIMARY REGISTERS)
# =============================================================================
EXTRACTION_PROMPTS = {
    "RORC": """You are reading a company's Register of Registrable Controllers (RORC),
maintained under Part 11A of the Singapore Companies Act 1967.

Extract every controller entry. For each entry, return:
- name
- type: "individual" or "corporate"
- nationality_or_jurisdiction
- nature_of_control (as stated)
- percentage (number if stated, otherwise null)
- date_became_controller
- confirmed: true/false (whether particulars were confirmed; default true if not mentioned)

Respond ONLY with valid JSON, no other text:
{
  "document_type": "RORC",
  "company_name": "...",
  "entries": [
    {"name": "...", "type": "...", "nationality_or_jurisdiction": "...", "nature_of_control": "...", "percentage": ..., "date_became_controller": "...", "confirmed": true}
  ]
}""",

    "ROND": """You are reading a company's Register of Nominee Directors (ROND),
maintained under Part 11A of the Singapore Companies Act 1967.

Extract every entry. For each entry, return:
- nominee_director_name
- nominator_name
- nominator_type: "individual" or "corporate"
- nominator_nationality_or_jurisdiction
- date_became_nominee_director

Respond ONLY with valid JSON, no other text:
{
  "document_type": "ROND",
  "company_name": "...",
  "entries": [
    {"nominee_director_name": "...", "nominator_name": "...", "nominator_type": "...", "nominator_nationality_or_jurisdiction": "...", "date_became_nominee_director": "..."}
  ]
}""",

    "RONS": """You are reading a company's Register of Nominee Shareholders (RONS),
maintained under Part 11A of the Singapore Companies Act 1967.

Extract every entry. For each entry, return:
- nominee_shareholder_name
- nominator_name
- nominator_type: "individual" or "corporate"
- nominator_nationality_or_jurisdiction
- shares_held_as_nominee (description, if stated)
- date_became_nominee_shareholder

Respond ONLY with valid JSON, no other text:
{
  "document_type": "RONS",
  "company_name": "...",
  "entries": [
    {"nominee_shareholder_name": "...", "nominator_name": "...", "nominator_type": "...", "nominator_nationality_or_jurisdiction": "...", "shares_held_as_nominee": "...", "date_became_nominee_shareholder": "..."}
  ]
}""",

    "Register of Members": """You are reading a company's Register of Members
(shareholder register), maintained under the Singapore Companies Act 1967.

Extract every shareholder entry. For each entry, return:
- shareholder_name
- shareholder_type: "individual" or "corporate"
- number_of_shares
- share_class (if stated, otherwise "Ordinary")
- percentage_of_total (calculate if derivable, otherwise null)
- voting_rights_percentage (if different from shareholding, otherwise same)

Respond ONLY with valid JSON, no other text:
{
  "document_type": "Register of Members",
  "company_name": "...",
  "total_shares": ...,
  "entries": [
    {"shareholder_name": "...", "shareholder_type": "...", "number_of_shares": ..., "share_class": "...", "percentage_of_total": ..., "voting_rights_percentage": ...}
  ]
}""",
}


# =============================================================================
# EXTRACTION PROMPT — STAGE 2 (SUPPORTING DOCUMENTS)
# =============================================================================
SUPPORTING_DOC_PROMPT = """You are reading a supporting document submitted to substantiate a
beneficial ownership claim under Singapore's Part 11A Companies Act 1967
framework. The document may be an NRIC, passport, ACRA Bizfile / business
profile extract, certificate of incorporation, or similar.

Identify what type of document this is and extract the key fields. Return:
- doc_category: one of "identity_individual" (NRIC/passport), "corporate_profile" (Bizfile/cert of incorp), "address_verification", "other"
- subject_name: the name of the individual or entity this document is about
- nationality_or_jurisdiction
- identifier (NRIC/passport number, or UEN/registration number)
- key_facts: a short list of strings describing other relevant facts found (e.g. "100% shareholder: Sarah Lim", "Entity type: Private Company Limited by Shares", "Registered address: ...")

Respond ONLY with valid JSON, no other text:
{
  "doc_category": "...",
  "subject_name": "...",
  "nationality_or_jurisdiction": "...",
  "identifier": "...",
  "key_facts": ["...", "..."]
}"""


# =============================================================================
# RORC EXEMPTION CATEGORIES (Section 6 of PRD)
# =============================================================================
EXEMPTION_CATEGORIES = [
    {
        "id": "sgx_listed",
        "label": "Public company listed on SGX",
        "basis": "s.386AA(1) read with 14th Schedule, Companies Act 1967",
        "evidence": "SGX listing printout / Bizfile showing listed status",
    },
    {
        "id": "sg_fi",
        "label": "Singapore financial institution",
        "basis": "14th Schedule para 2, Companies Act 1967",
        "evidence": "MAS Financial Institutions Directory entry or MAS licence confirmation",
    },
    {
        "id": "govt_owned",
        "label": "Wholly owned by Singapore Government",
        "basis": "14th Schedule, Companies Act 1967",
        "evidence": "ACRA business profile confirming government ownership",
    },
    {
        "id": "statutory_body",
        "label": "Wholly owned by a statutory body (public Act, public purpose)",
        "basis": "14th Schedule, Companies Act 1967",
        "evidence": "ACRA business profile; reference to constituting statute",
    },
    {
        "id": "wos_exempt_parent",
        "label": "Wholly-owned subsidiary of an exempt entity above",
        "basis": "14th Schedule read with s.5B, Companies Act 1967",
        "evidence": "ACRA business profile + evidence of 100% ownership by exempt parent",
    },
    {
        "id": "foreign_listed",
        "label": "Listed on a foreign exchange with adequate BO transparency",
        "basis": "14th Schedule para (vi), Companies Act 1967",
        "evidence": "Listing evidence (requires legal confirmation of adequacy — soft stop)",
    },
    {
        "id": "sgx_corp_sfa",
        "label": "SGX-listed corporation (SFA definition)",
        "basis": "s.386AC(c)(iv), Companies Act 1967",
        "evidence": "SGX listing printout",
    },
    {
        "id": "llp_own_rorc",
        "label": "LLP required to maintain its own RORC",
        "basis": "s.386AC(c)(v), Companies Act 1967",
        "evidence": "ACRA business profile showing LLP status (not itself exempt)",
    },
    {
        "id": "llp_exempt",
        "label": "LLP exempt from RORC under 6th Schedule to LLP Act 2005",
        "basis": "s.386AC(c)(vi), Companies Act 1967",
        "evidence": "Evidence of LLP's exempt status",
    },
    {
        "id": "trustee",
        "label": "Trustee of an express trust under Part 7, Trustees Act 1967",
        "basis": "s.386AC(c)(vii), Companies Act 1967",
        "evidence": "Trust deed; evidence trustee acting in that capacity",
    },
    {
        "id": "vcc",
        "label": "Variable Capital Company (VCC)",
        "basis": "s.386AC(c)(viii), Companies Act 1967",
        "evidence": "ACRA business profile showing VCC status",
    },
    {
        "id": "none",
        "label": "None of the above — not exempt",
        "basis": "-",
        "evidence": "-",
    },
]

CONTROL_MECHANISMS = [
    "Significant interest - direct shareholding (>25% shares)",
    "Significant interest - direct voting power (>25% voting rights)",
    "Significant control - right to appoint/remove majority of directors",
    "Significant control - >25% of member voting rights",
    "Significant control - significant influence or control",
    "Indirect holding - majority stake in intermediate entity",
    "Nominee arrangement - beneficial owner behind nominee shareholder",
    "Joint arrangement - combined holding via arrangement",
    "Fallback - director with executive control / CEO (s.386AFA)",
]


# =============================================================================
# HELPERS — API CALLS
# =============================================================================
def extract_document(client, prompt, file_bytes):
    """Send a PDF to Claude for structured extraction using the given prompt."""
    b64 = base64.standard_b64encode(file_bytes).decode("utf-8")
    message = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    text = "".join(block.text for block in message.content if block.type == "text").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


# =============================================================================
# STAGE 1 — FIRST-CUT CROSS-CHECK
# =============================================================================
def run_first_cut_checks(data):
    """
    Returns:
      flags: list of flag dicts for display
      candidates: list of candidate controller dicts requiring Stage 2 action
        each candidate: {
          "id": unique string,
          "name": str,
          "type": "individual"/"corporate",
          "source": "RORC" / "RONS-nominator" / "ROM-gap",
          "reason": str,
          "percentage": float or None,
          "nominee_name": str or None (if via nominee),
          "needs_clarification": bool (the yes/no nominator question),
        }
    """
    flags = []
    candidates = []

    rorc = data.get("RORC", {}).get("entries", [])
    rond = data.get("ROND", {}).get("entries", [])
    rons = data.get("RONS", {}).get("entries", [])
    rom = data.get("Register of Members", {}).get("entries", [])

    rorc_names = {e["name"].strip().lower() for e in rorc}

    # Existing RORC entries become baseline candidates (already controllers)
    for e in rorc:
        candidates.append({
            "id": f"rorc::{e['name']}",
            "name": e["name"],
            "type": e["type"],
            "source": "RORC",
            "reason": f"Listed in RORC — {e['nature_of_control']}"
                      + (f" ({e['percentage']}%)" if e.get("percentage") else ""),
            "percentage": e.get("percentage"),
            "nominee_name": None,
            "needs_clarification": False,
            "confirmed": e.get("confirmed", True),
        })

    # 1. RORC vs ROND
    for e in rond:
        nominee_name = e["nominee_director_name"].strip().lower()
        if nominee_name in rorc_names:
            flags.append({
                "severity": "info",
                "title": "Nominee director also listed as RORC controller",
                "detail": (
                    f"'{e['nominee_director_name']}' appears in both the RORC and the ROND "
                    f"(as a nominee director acting for {e['nominator_name']}). Being a "
                    f"nominee director does not by itself make someone a registrable "
                    f"controller (RORC Guidance v2.0 para 2.0.3) — the RORC entry must be "
                    f"based on a separate control basis, which Stage 2 will validate."
                ),
                "rule": "R-14",
            })

    # 2 & 3. RORC vs RONS, and RORC vs Register of Members
    for e in rons:
        nominator_name = e["nominator_name"].strip()
        nominee_name = e["nominee_shareholder_name"].strip().lower()

        nominee_holding = next(
            (m for m in rom if m["shareholder_name"].strip().lower() == nominee_name),
            None,
        )
        pct = nominee_holding["percentage_of_total"] if nominee_holding else None

        if nominator_name.strip().lower() not in rorc_names:
            if pct is not None and pct >= 25:
                flags.append({
                    "severity": "high",
                    "title": f"Possible missing controller — {e['nominee_shareholder_name']} holds {pct}% as nominee",
                    "detail": (
                        f"The Register of Members shows '{e['nominee_shareholder_name']}' holds "
                        f"{pct}% of shares, which would meet the >25% significant interest "
                        f"threshold under the Sixteenth Schedule, Companies Act 1967. However, "
                        f"the RONS shows '{e['nominee_shareholder_name']}' is a nominee "
                        f"shareholder, and records '{nominator_name}' as the nominator on "
                        f"whose behalf the shares are held. The nominator is not currently in "
                        f"the RORC. Under RORC Guidance v2.0 para 7.14, shares held by a "
                        f"nominee are treated as held by the person for whom the nominee acts "
                        f"— but the nominator named in the RONS is not necessarily the same "
                        f"as the ultimate beneficial owner. This will be clarified in Stage 2."
                    ),
                    "rule": "R-11 / R-15",
                })
                candidates.append({
                    "id": f"rons::{nominator_name}",
                    "name": nominator_name,
                    "type": e["nominator_type"],
                    "source": "RONS-nominator",
                    "reason": (
                        f"Named as nominator behind '{e['nominee_shareholder_name']}', which "
                        f"holds {pct}% of shares (meets >25% threshold)"
                    ),
                    "percentage": pct,
                    "nominee_name": e["nominee_shareholder_name"],
                    "needs_clarification": True,
                    "confirmed": True,
                })
            else:
                flags.append({
                    "severity": "info",
                    "title": "Nominee shareholder's nominator not in RORC",
                    "detail": (
                        f"'{nominator_name}' is the nominator behind nominee shareholder "
                        f"'{e['nominee_shareholder_name']}' but does not appear in the RORC. "
                        f"Based on the Register of Members this holding does not appear to "
                        f"meet the >25% threshold on its own. Please confirm whether "
                        f"'{nominator_name}' has significant control by other means "
                        f"(RONS Guidance v2.0 para 2.0.3)."
                    ),
                    "rule": "R-15",
                })

    for m in rom:
        pct = m.get("percentage_of_total")
        name = m["shareholder_name"].strip().lower()
        if pct is not None and pct >= 25 and name not in rorc_names:
            is_nominee = any(
                e["nominee_shareholder_name"].strip().lower() == name for e in rons
            )
            if not is_nominee:
                flags.append({
                    "severity": "high",
                    "title": f"Shareholder above 25% not listed in RORC: {m['shareholder_name']}",
                    "detail": (
                        f"'{m['shareholder_name']}' holds {pct}% of shares per the Register "
                        f"of Members, which meets the >25% significant interest threshold "
                        f"(Companies Act 1967, Sixteenth Schedule), but does not appear in "
                        f"the RORC. Please confirm whether this is an oversight or whether "
                        f"this shareholder is exempt or held via an undisclosed arrangement."
                    ),
                    "rule": "R-01",
                })
                candidates.append({
                    "id": f"rom-gap::{m['shareholder_name']}",
                    "name": m["shareholder_name"],
                    "type": m["shareholder_type"].lower().replace(" (nominee)", ""),
                    "source": "ROM-gap",
                    "reason": f"Holds {pct}% per Register of Members but not in RORC",
                    "percentage": pct,
                    "nominee_name": None,
                    "needs_clarification": False,
                    "confirmed": True,
                })

    # 4. All-corporate check / corporate tracing flags
    if rorc and all(e["type"] == "corporate" for e in rorc):
        flags.append({
            "severity": "high",
            "title": "All listed controllers are corporate entities",
            "detail": (
                "Every entry in the RORC is a corporate entity. Singapore law and FATF "
                "standards require tracing through to a natural person (or a recognised "
                "RORC-exempt entity) under s.386AC of the Companies Act 1967. Stage 2 will "
                "guide you through tracing each corporate controller upward."
            ),
            "rule": "R-06",
        })
    for e in rorc:
        if e["type"] == "corporate":
            flags.append({
                "severity": "medium",
                "title": f"Corporate controller requires tracing: {e['name']}",
                "detail": (
                    f"'{e['name']}' is listed as a corporate controller. Under s.386AC of the "
                    f"Companies Act 1967, the chain must be traced to a natural person or a "
                    f"recognised RORC-exempt entity. Stage 2 will request documents to trace "
                    f"this entity's ownership."
                ),
                "rule": "R-06",
            })

    # 5. Unconfirmed particulars
    for e in rorc:
        if not e.get("confirmed", True):
            flags.append({
                "severity": "medium",
                "title": f"Unconfirmed particulars: {e['name']}",
                "detail": (
                    f"'{e['name']}' is marked as not having confirmed their particulars. "
                    f"Under s.386AF(9) and s.386AG of the Companies Act 1967, this entry "
                    f"may still be filed but must be noted as unconfirmed. Please retain "
                    f"evidence that the annual notice was sent to this controller "
                    f"(RORC Guidance v2.0 para 5.1.6)."
                ),
                "rule": "R-13",
            })

    if not flags:
        flags.append({
            "severity": "ok",
            "title": "No first-cut issues identified",
            "detail": "The RORC, ROND, RONS and Register of Members appear consistent at this stage.",
            "rule": "-",
        })

    return flags, candidates


SEVERITY_STYLE = {
    "high": ("🔴", "High priority"),
    "medium": ("🟠", "Needs review"),
    "info": ("🔵", "For your information"),
    "ok": ("🟢", "OK"),
}


# =============================================================================
# STAGE 3 — REPORT GENERATION (PDF)
# =============================================================================
def generate_report_pdf(company_name, uen, extracted, flags, controllers):
    """Build the downloadable PDF report described in PRD Section 8."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("T", parent=styles["Title"], fontSize=18, spaceAfter=4)
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=14, textColor=colors.HexColor("#1F4E79"), spaceBefore=14, spaceAfter=6)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, textColor=colors.HexColor("#2E75B6"), spaceBefore=10, spaceAfter=4)
    normal = styles["Normal"]
    small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    cite = ParagraphStyle("Cite", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#7F7F7F"), spaceAfter=8)

    story = []

    # Cover
    story.append(Paragraph("SG Beneficial Ownership Validation Report", title_style))
    story.append(Paragraph(f"{company_name}" + (f" (UEN: {uen})" if uen else ""), normal))
    story.append(Paragraph(f"Date of validation: {date.today().strftime('%d %B %Y')}", small))
    story.append(Spacer(1, 12))

    overall_status = "PASS"
    high_flags = [f for f in flags if f["severity"] == "high"]
    medium_flags = [f for f in flags if f["severity"] == "medium"]
    unresolved_gaps = [c for c in controllers if c.get("validation_status") == "Gap identified"]
    if high_flags or unresolved_gaps:
        overall_status = "PASS WITH GAPS" if not high_flags or len(unresolved_gaps) < len(controllers) else "FAIL"
        if high_flags and unresolved_gaps:
            overall_status = "PASS WITH GAPS"
    status_color = {"PASS": colors.green, "PASS WITH GAPS": colors.orange, "FAIL": colors.red}[overall_status]
    story.append(Paragraph(f"<b>Overall status: <font color='{status_color.hexval()}'>{overall_status}</font></b>", normal))
    story.append(Spacer(1, 6))

    story.append(Paragraph(
        "This report summarises a self-assessment of whether the supporting documents "
        "provided are sufficient to substantiate the company's beneficial ownership "
        "filings, based on Part 11A of the Companies Act 1967 and ACRA guidance "
        "(last checked June 2026). It is intended to accompany supporting documents "
        "submitted to ACRA and to serve as the written explanation of those documents.",
        normal
    ))

    story.append(PageBreak())

    # Document summary
    story.append(Paragraph("1. Document Summary", h1))
    doc_table_data = [["Document", "Company name found", "Entries found"]]
    for doc_type in ["RORC", "ROND", "RONS", "Register of Members"]:
        d = extracted.get(doc_type, {})
        doc_table_data.append([
            doc_type,
            d.get("company_name", "-"),
            str(len(d.get("entries", []))),
        ])
    t = Table(doc_table_data, colWidths=[2.2*inch, 2.8*inch, 1.5*inch])
    t.setStyle(_table_style())
    story.append(t)
    story.append(Spacer(1, 10))

    # First-cut flags
    story.append(Paragraph("2. First-Cut Cross-Check Findings", h1))
    for f in flags:
        icon, label = SEVERITY_STYLE[f["severity"]]
        story.append(Paragraph(f"<b>{icon} {f['title']}</b> ({label})", h2))
        story.append(Paragraph(f["detail"], normal))
        story.append(Paragraph(f"Rule reference: {f['rule']}", cite))

    story.append(PageBreak())

    # Controller-by-controller analysis
    story.append(Paragraph("3. Controller-by-Controller Analysis", h1))
    for c in controllers:
        story.append(Paragraph(f"{c['name']} ({c['type'].title()})", h2))
        ctrl_table = [
            ["Mechanism of control", c.get("mechanism", "Not yet determined")],
            ["Source", c.get("reason", "-")],
            ["Supporting documents", c.get("documents_summary", "None provided")],
            ["Validation status", c.get("validation_status", "Pending")],
        ]
        if c.get("gap_detail"):
            ctrl_table.append(["Gap identified", c["gap_detail"]])
        if c.get("chain_termination"):
            ctrl_table.append(["Chain termination", c["chain_termination"]])
        t = Table(ctrl_table, colWidths=[1.8*inch, 4.7*inch])
        t.setStyle(_table_style(header=False))
        story.append(t)
        story.append(Spacer(1, 8))

    story.append(PageBreak())

    # Gaps & recommendations
    story.append(Paragraph("4. Gaps & Recommendations", h1))
    gaps = [c for c in controllers if c.get("validation_status") == "Gap identified"]
    if gaps:
        for c in gaps:
            story.append(Paragraph(f"<b>{c['name']}</b>: {c.get('gap_detail', 'Documentation incomplete.')}", normal))
            story.append(Paragraph(f"Recommended action: {c.get('recommendation', 'Provide the missing supporting document(s) listed above.')}", cite))
    else:
        story.append(Paragraph("No outstanding gaps identified based on the documents and confirmations provided.", normal))

    story.append(Spacer(1, 10))

    # Regulatory basis
    story.append(Paragraph("5. Regulatory Basis (Source Last Checked: June 2026)", h1))
    rules_table = [
        ["Rule", "Source"],
        ["R-01 Significant interest threshold (>25% shares/voting)", "Companies Act 1967, Sixteenth Schedule"],
        ["R-06 Registrability / tracing requirement", "Companies Act 1967 s.386AC"],
        ["R-11 Nominee holdings treated as held by nominator", "RORC Guidance v2.0 para 7.14"],
        ["R-12 Fallback to directors with executive control / CEO", "Companies Act 1967 s.386AFA"],
        ["R-13 Unconfirmed particulars may be filed with note", "Companies Act 1967 ss.386AF(9), 386AG"],
        ["R-14 Nominee director status alone is not controllership", "RORC Guidance v2.0 para 2.0.3"],
        ["R-15 Nominee shareholder nominator threshold test", "RONS Guidance v2.0 para 2.0.3"],
        ["RORC exemption categories (Section 6)", "Companies Act 1967 s.386AC(c), 14th/15th Schedule"],
    ]
    t = Table(rules_table, colWidths=[4.2*inch, 2.3*inch])
    t.setStyle(_table_style())
    story.append(t)

    story.append(Spacer(1, 14))

    # Disclaimer
    story.append(Paragraph("6. Disclaimer", h1))
    story.append(Paragraph(
        "This report is a document sufficiency self-assessment generated by an AI-assisted "
        "tool based on encoded rules derived from the Companies Act 1967 and ACRA guidance "
        "as at June 2026. It does not constitute legal advice. The company should review "
        "this report with a qualified professional (e.g. a corporate service provider, "
        "company secretary, or legal counsel) before submitting documents and explanations "
        "to ACRA.",
        normal
    ))

    doc.build(story)
    buf.seek(0)
    return buf


def _table_style(header=True):
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
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


# =============================================================================
# SESSION STATE INIT
# =============================================================================
DEFAULTS = {
    "stage": 1,
    "extracted": {},
    "confirmed": {},
    "flags": None,
    "candidates": [],
    "controllers": {},     # id -> controller dict (working state through stages 2-3)
    "company_name": "",
    "company_uen": "",
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

DOC_TYPES = ["RORC", "ROND", "RONS", "Register of Members"]


# =============================================================================
# SIDEBAR
# =============================================================================
with st.sidebar:
    st.title("🔎 SG BO Validator")
    st.caption("Prototype — Stages 1-3")
    st.markdown("---")

    stage_labels = {
        1: "1. Register upload & cross-check",
        2: "2. Supporting document validation",
        3: "3. Ownership chain & report",
    }
    for s, label in stage_labels.items():
        if s == st.session_state.stage:
            st.markdown(f"**➡ {label}**")
        elif s < st.session_state.stage:
            st.markdown(f"✅ {label}")
        else:
            st.markdown(f"⬜ {label}")

    st.markdown("---")
    st.markdown(
        "**Privacy notice**\n\n"
        "Uploaded documents are sent to the Anthropic API for parsing only. "
        "Nothing is stored server-side. Closing this session clears everything."
    )
    st.markdown("---")
    st.caption(
        "This is a prototype for internal demo purposes. It is not legal "
        "advice and should not be used to make filing decisions without "
        "professional review."
    )

    if st.session_state.stage > 1:
        st.markdown("---")
        if st.button("⬅ Back to Stage " + str(st.session_state.stage - 1)):
            st.session_state.stage -= 1
            st.rerun()

    st.markdown("---")
    if st.button("🔄 Restart session"):
        for k, v in DEFAULTS.items():
            st.session_state[k] = v
        st.rerun()


# =============================================================================
# STAGE 1 — REGISTER UPLOAD & FIRST-CUT CROSS-CHECK
# =============================================================================
def stage_1():
    st.title("Stage 1 — Register Upload & First-Cut Cross-Check")
    st.markdown(
        "Upload the four primary registers below (PDF format). The AI will "
        "read each document, extract the key details, and ask you to confirm "
        "what it found before running a cross-check."
    )

    c1, c2 = st.columns(2)
    with c1:
        st.session_state.company_name = st.text_input("Company name", value=st.session_state.company_name)
    with c2:
        st.session_state.company_uen = st.text_input("UEN (optional)", value=st.session_state.company_uen)

    st.markdown("---")

    cols = st.columns(4)
    uploaded_files = {}
    for i, doc_type in enumerate(DOC_TYPES):
        with cols[i]:
            uploaded_files[doc_type] = st.file_uploader(doc_type, type=["pdf"], key=f"upload_{doc_type}")

    st.markdown("---")

    if st.button("Parse documents", type="primary"):
        missing = [d for d in DOC_TYPES if uploaded_files[d] is None]
        if missing:
            st.warning(f"Please upload all four documents. Missing: {', '.join(missing)}")
        else:
            client = get_client()
            with st.spinner("Reading documents with Claude..."):
                for doc_type in DOC_TYPES:
                    file_bytes = uploaded_files[doc_type].read()
                    try:
                        result = extract_document(client, EXTRACTION_PROMPTS[doc_type], file_bytes)
                        st.session_state.extracted[doc_type] = result
                    except Exception as e:
                        st.error(f"Could not parse {doc_type}: {e}")
            st.session_state.flags = None
            st.session_state.candidates = []
            st.success("Documents parsed. Please review the extracted information below.")

    # Review extracted data
    if st.session_state.extracted:
        st.markdown("## Review extracted information")
        st.caption("Please check the AI's reading of each document.")

        for doc_type in DOC_TYPES:
            if doc_type not in st.session_state.extracted:
                continue
            data = st.session_state.extracted[doc_type]
            with st.expander(f"📄 {doc_type} — {data.get('company_name', 'Unknown company')}", expanded=True):
                entries = data.get("entries", [])
                if entries:
                    st.dataframe(entries, use_container_width=True)
                else:
                    st.info("No entries found in this document.")
                st.session_state.confirmed[doc_type] = st.checkbox(
                    f"I confirm this is an accurate reading of the {doc_type}",
                    key=f"confirm_{doc_type}",
                )

        all_confirmed = (
            len(st.session_state.extracted) == 4
            and all(st.session_state.confirmed.get(d, False) for d in DOC_TYPES)
        )

        st.markdown("---")
        if st.button("Run first-cut cross-check", type="primary", disabled=not all_confirmed):
            flags, candidates = run_first_cut_checks(st.session_state.extracted)
            st.session_state.flags = flags
            st.session_state.candidates = candidates

            # initialise controllers dict for stage 2/3
            for c in candidates:
                if c["id"] not in st.session_state.controllers:
                    st.session_state.controllers[c["id"]] = {
                        **c,
                        "mechanism": c["reason"],
                        "documents": [],
                        "documents_summary": "None provided",
                        "validation_status": "Pending",
                        "gap_detail": None,
                        "recommendation": None,
                        "chain_termination": None,
                        "resolved_beneficial_owner": None,  # used for RONS-nominator branching
                    }

        if not all_confirmed:
            st.caption("Please confirm all four documents above before running the cross-check.")

    # Cross-check results
    if st.session_state.flags:
        st.markdown("## First-cut cross-check results")
        st.caption(
            "These checks compare your RORC, ROND, RONS and Register of Members "
            "against each other (Companies Act 1967 and ACRA guidance, last "
            "checked June 2026)."
        )
        for flag in st.session_state.flags:
            icon, label = SEVERITY_STYLE[flag["severity"]]
            with st.container(border=True):
                st.markdown(f"### {icon} {flag['title']}")
                st.write(flag["detail"])
                st.caption(f"Rule reference: {flag['rule']}")

        st.markdown("---")
        if st.button("Proceed to Stage 2 — Supporting documents ➡", type="primary"):
            st.session_state.stage = 2
            st.rerun()


# =============================================================================
# STAGE 2 — SUPPORTING DOCUMENT VALIDATION
# =============================================================================
def stage_2():
    st.title("Stage 2 — Supporting Document Validation")
    st.markdown(
        "For each candidate controller identified in Stage 1, please answer "
        "any clarifying questions and upload supporting documents. The AI "
        "will read each document and check it against the claimed details."
    )

    controllers = st.session_state.controllers
    if not controllers:
        st.info("No candidate controllers were identified. You can proceed to Stage 3.")
    else:
        for cid, c in controllers.items():
            with st.container(border=True):
                st.markdown(f"### {c['name']} ({c['type'].title()})")
                st.caption(c["reason"])

                # --- Clarifying yes/no question for RONS-nominator candidates ---
                if c["source"] == "RONS-nominator":
                    st.markdown(
                        f"**Clarifying question:** The Register of Members shows "
                        f"'{c['nominee_name']}' holds {c['percentage']}% of shares, which "
                        f"would meet the >25% significant interest threshold. The RONS "
                        f"records **{c['name']}** as the nominator on whose behalf "
                        f"'{c['nominee_name']}' holds these shares."
                    )
                    answer_key = f"clarify_{cid}"
                    answer = st.radio(
                        f"Is **{c['name']}** the beneficial owner of this {c['percentage']}% interest "
                        f"(i.e. does {c['name']} ultimately benefit from and/or control these shares), "
                        f"or does {c['name']} hold them on behalf of someone else?",
                        options=["Yes — " + c['name'] + " is the beneficial owner",
                                 "No — someone else is the beneficial owner"],
                        key=answer_key,
                        index=None,
                    )

                    if answer and answer.startswith("Yes"):
                        c["resolved_beneficial_owner"] = {"name": c["name"], "type": c["type"]}
                        c["mechanism"] = (
                            f"Nominee arrangement — {c['name']} is the beneficial owner behind "
                            f"nominee shareholder '{c['nominee_name']}' "
                            f"({c['percentage']}% of shares), per RONS Guidance v2.0 para 7.14"
                        )
                    elif answer and answer.startswith("No"):
                        other_name = st.text_input(
                            f"Who is the actual beneficial owner of the {c['percentage']}% interest "
                            f"held via '{c['nominee_name']}'?",
                            key=f"other_name_{cid}",
                        )
                        other_type = st.selectbox(
                            "Type", ["individual", "corporate"], key=f"other_type_{cid}"
                        )
                        if other_name:
                            c["resolved_beneficial_owner"] = {"name": other_name, "type": other_type}
                            c["mechanism"] = (
                                f"Nominee arrangement — RONS names {c['name']} as nominator behind "
                                f"'{c['nominee_name']}' ({c['percentage']}% of shares), but the "
                                f"actual beneficial owner has been identified as {other_name}. "
                                f"This discrepancy between the RONS-stated nominator and the "
                                f"actual beneficial owner should be documented in the written "
                                f"explanation submitted to ACRA, per RONS Guidance v2.0 para 2.0.3 "
                                f"and RORC Guidance v2.0 para 7.14."
                            )
                            st.warning(
                                f"Noted: RONS names {c['name']} as nominator, but you have "
                                f"identified {other_name} as the actual beneficial owner. "
                                f"This will be flagged as a discrepancy to explain in the report."
                            )
                    if answer is None:
                        st.info("Please answer the question above to proceed with this controller.")

                # --- Document type guidance ---
                doc_guidance = _document_guidance_for(c)
                st.markdown(f"**Supporting documents needed:** {doc_guidance}")

                # --- File upload + parsing ---
                uploaded = st.file_uploader(
                    f"Upload supporting document(s) for {c['name']}",
                    type=["pdf"], accept_multiple_files=True, key=f"docs_{cid}",
                )

                if uploaded and st.button(f"Parse documents for {c['name']}", key=f"parse_{cid}"):
                    client = get_client()
                    parsed_docs = []
                    with st.spinner("Reading documents with Claude..."):
                        for f in uploaded:
                            try:
                                result = extract_document(client, SUPPORTING_DOC_PROMPT, f.read())
                                parsed_docs.append({"filename": f.name, **result})
                            except Exception as e:
                                st.error(f"Could not parse {f.name}: {e}")
                    c["documents"] = parsed_docs
                    c["documents_summary"] = "; ".join(
                        f"{d['filename']} ({d['doc_category']}, subject: {d['subject_name']})"
                        for d in parsed_docs
                    ) if parsed_docs else "None provided"

                if c["documents"]:
                    st.markdown("**Parsed supporting documents:**")
                    for d in c["documents"]:
                        with st.expander(f"📄 {d['filename']}"):
                            st.json(d)
                        confirm_key = f"doc_confirm_{cid}_{d['filename']}"
                        st.checkbox(f"I confirm this reading of {d['filename']} is accurate", key=confirm_key)

                # --- Exemption category check (for corporate controllers requiring tracing) ---
                if c["type"] == "corporate" and c["source"] in ("RORC", "rom-gap", "ROM-gap"):
                    st.markdown("**Tracing check:** Does this corporate controller fall into any RORC-exemption category, or does it need to be traced further to a natural person?")
                    exemption_choice = st.selectbox(
                        "Select the applicable exemption category (or 'None' if tracing is required)",
                        options=[e["label"] for e in EXEMPTION_CATEGORIES],
                        key=f"exemption_{cid}",
                    )
                    chosen = next(e for e in EXEMPTION_CATEGORIES if e["label"] == exemption_choice)
                    c["exemption"] = chosen

                    if chosen["id"] == "none":
                        st.info(
                            "Tracing required: please confirm whether a natural person has "
                            "been identified upstream and add them as an additional "
                            "controller below."
                        )
                        st.markdown("**Add the natural person (or further entity) found by tracing:**")
                        trace_name = st.text_input("Name", key=f"trace_name_{cid}")
                        trace_type = st.selectbox("Type", ["individual", "corporate"], key=f"trace_type_{cid}")
                        trace_pct = st.number_input("Effective % interest in this company (if known)", min_value=0.0, max_value=100.0, value=0.0, key=f"trace_pct_{cid}")
                        if trace_name and st.button(f"Add traced entity for {c['name']}", key=f"add_trace_{cid}"):
                            new_id = f"traced::{cid}::{trace_name}"
                            controllers[new_id] = {
                                "id": new_id,
                                "name": trace_name,
                                "type": trace_type,
                                "source": f"Traced via {c['name']}",
                                "reason": f"Identified by tracing {c['name']} upward (s.386AC, Companies Act 1967)",
                                "percentage": trace_pct if trace_pct else None,
                                "nominee_name": None,
                                "needs_clarification": False,
                                "confirmed": True,
                                "mechanism": f"Indirect holding — traced via {c['name']} (RORC Guidance v2.0 para 7.10)",
                                "documents": [],
                                "documents_summary": "None provided",
                                "validation_status": "Pending",
                                "gap_detail": None,
                                "recommendation": None,
                                "chain_termination": None,
                                "resolved_beneficial_owner": None,
                                "exemption": None,
                            }
                            st.success(f"Added {trace_name} as a traced controller. Scroll down to provide their supporting documents.")
                            st.rerun()
                    else:
                        c["chain_termination"] = (
                            f"Chain terminates here — {c['name']} falls within the exemption "
                            f"category '{chosen['label']}' ({chosen['basis']}). "
                            f"Evidence required: {chosen['evidence']}."
                        )
                        if chosen["id"] == "foreign_listed":
                            st.warning(
                                "Note: the adequacy of a foreign exchange's BO transparency "
                                "requirements is a legal question. This tool flags the chain "
                                "as terminating here but recommends confirming adequacy with "
                                "legal counsel before relying on this exemption."
                            )
                        st.info(c["chain_termination"])

                # --- Validation status determination ---
                _update_validation_status(c)
                status = c["validation_status"]
                status_color = {"Validated": "🟢", "Partially Validated": "🟡", "Gap identified": "🔴", "Pending": "⚪"}
                st.markdown(f"**Validation status:** {status_color.get(status, '⚪')} {status}")
                if c.get("gap_detail"):
                    st.caption(f"Gap: {c['gap_detail']}")

    st.markdown("---")
    if st.button("Proceed to Stage 3 — Ownership chain & report ➡", type="primary"):
        st.session_state.stage = 3
        st.rerun()


def _document_guidance_for(c):
    """Returns a short text describing what documents are expected, per PRD Section 4.2."""
    if c["source"] == "RONS-nominator":
        return (
            "Identity document (NRIC for Singapore citizens/PRs, or passport + address "
            "verification for foreign nationals) for the confirmed beneficial owner, "
            "plus any correspondence/agreement evidencing the nominee relationship."
        )
    if c["type"] == "individual":
        return "Copy of NRIC (Singapore citizens/PRs) or passport + address verification document (foreign nationals)."
    if c["type"] == "corporate":
        return (
            "ACRA business profile / certificate of incorporation for this entity, "
            "and (if tracing further) documents for its own shareholders/controllers."
        )
    return "Relevant identity or registration documents."


def _update_validation_status(c):
    """Simple status logic: Validated if docs provided + confirmed; gap otherwise."""
    if c["source"] == "RONS-nominator" and c.get("resolved_beneficial_owner") is None:
        c["validation_status"] = "Gap identified"
        c["gap_detail"] = "Clarifying question not yet answered (is the RONS-named nominator the beneficial owner?)."
        c["recommendation"] = "Answer the clarifying question above to identify the correct beneficial owner."
        return

    if c["type"] == "corporate" and c.get("exemption") is None and c["source"] in ("RORC", "ROM-gap", "rom-gap"):
        c["validation_status"] = "Gap identified"
        c["gap_detail"] = "Tracing/exemption status not yet determined for this corporate controller."
        c["recommendation"] = "Select the applicable exemption category, or trace to a natural person above."
        return

    if c["type"] == "corporate" and c.get("exemption") and c["exemption"]["id"] == "none" and not c.get("documents"):
        c["validation_status"] = "Partially Validated"
        c["gap_detail"] = f"Tracing in progress for {c['name']}; supporting documents for the next layer not yet provided."
        c["recommendation"] = f"Upload {c['exemption']['evidence'] if c['exemption'] else 'supporting documents'} for the traced entity."
        return

    if not c.get("documents"):
        c["validation_status"] = "Gap identified"
        c["gap_detail"] = f"No supporting documents uploaded for {c['name']}."
        c["recommendation"] = f"Upload: {_document_guidance_for(c)}"
        return

    c["validation_status"] = "Validated"
    c["gap_detail"] = None
    c["recommendation"] = None


# =============================================================================
# STAGE 3 — OWNERSHIP CHAIN & REPORT
# =============================================================================
def stage_3():
    st.title("Stage 3 — Ownership Chain & Validation Report")

    controllers = list(st.session_state.controllers.values())

    st.markdown("## Ownership chain")
    st.caption(
        f"Based on the documents provided for {st.session_state.company_name or 'this company'}, "
        "the following chain has been constructed:"
    )

    for c in controllers:
        with st.container(border=True):
            display_name = c["name"]
            if c["source"] == "RONS-nominator" and c.get("resolved_beneficial_owner"):
                display_name = c["resolved_beneficial_owner"]["name"]

            st.markdown(f"#### {display_name} ({c['type'].title()})")
            st.write(f"**Mechanism of control:** {c.get('mechanism', 'Not yet determined')}")
            st.write(f"**Documents:** {c.get('documents_summary', 'None provided')}")
            status = c.get("validation_status", "Pending")
            status_color = {"Validated": "🟢", "Partially Validated": "🟡", "Gap identified": "🔴", "Pending": "⚪"}
            st.write(f"**Status:** {status_color.get(status, '⚪')} {status}")
            if c.get("chain_termination"):
                st.success(c["chain_termination"])
            if c.get("gap_detail"):
                st.warning(f"Gap: {c['gap_detail']} — {c.get('recommendation', '')}")

    st.markdown("---")
    st.markdown("## Gap summary")
    gaps = [c for c in controllers if c.get("validation_status") == "Gap identified"]
    if gaps:
        for c in gaps:
            st.error(f"**{c['name']}**: {c['gap_detail']}\n\nRecommended action: {c['recommendation']}")
    else:
        st.success("No outstanding gaps identified based on the documents and confirmations provided.")

    st.markdown("---")
    st.markdown("## Download validation report")
    st.caption(
        "This report summarises the document review and ownership chain, and is "
        "structured to serve as the written explanation that accompanies "
        "supporting documents submitted to ACRA."
    )

    if st.button("Generate report", type="primary"):
        pdf_buf = generate_report_pdf(
            st.session_state.company_name or "Unnamed Company",
            st.session_state.company_uen,
            st.session_state.extracted,
            st.session_state.flags or [],
            controllers,
        )
        st.session_state["report_pdf"] = pdf_buf.getvalue()
        st.success("Report generated.")

    if "report_pdf" in st.session_state:
        st.download_button(
            "⬇ Download validation report (PDF)",
            data=st.session_state["report_pdf"],
            file_name=f"{(st.session_state.company_name or 'company').replace(' ', '_')}_BO_validation_report.pdf",
            mime="application/pdf",
        )


# =============================================================================
# ROUTER
# =============================================================================
if st.session_state.stage == 1:
    stage_1()
elif st.session_state.stage == 2:
    stage_2()
elif st.session_state.stage == 3:
    stage_3()
