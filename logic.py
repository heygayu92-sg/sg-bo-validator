"""
logic.py
========

Pure business logic for the SG BO Validator - no Streamlit UI code here,
so this module can be unit-tested independently.

Contains:
  - MECHANISM_OPTIONS / MECHANISM_RULE_BASIS: the Sixteenth Schedule
    mechanism-of-control dropdown options and their legal basis
  - DIRECT_INDIRECT_OPTIONS
  - EXEMPTION_CATEGORIES: the 11 RORC exemption categories (Section 6 of
    the PRD) used when tracing indirect/corporate controllers
  - entry_display_name / entry_key_id: helpers for naming/identifying RORC
    entries
  - cross_check_register_of_members: matches RORC entries against the
    Register of Members and finds unexplained >=25% holders
  - notice_status_flag: maps an annual notice status string to a
    (severity, label) tuple for display
"""


# =============================================================================
# MECHANISM OF CONTROL OPTIONS (Sixteenth Schedule, Companies Act 1967)
# =============================================================================
MECHANISM_OPTIONS = [
    "Holds more than 25% of shares (significant interest)",
    "Holds more than 25% of voting rights (significant interest)",
    "Holds more than 25% right to share in capital or profits - no share capital (significant interest)",
    "Right to appoint/remove directors holding majority of board voting rights (significant control)",
    "Holds more than 25% of member voting rights - e.g. company limited by guarantee (significant control)",
    "Has the right to exercise, or actually exercises, significant influence or control (significant control)",
    "Director with executive control / CEO - fallback (s.386AFA)",
    "Other",
]

MECHANISM_RULE_BASIS = {
    MECHANISM_OPTIONS[0]: "Sixteenth Schedule para 2, Companies Act 1967",
    MECHANISM_OPTIONS[1]: "Sixteenth Schedule para 2, Companies Act 1967",
    MECHANISM_OPTIONS[2]: "Sixteenth Schedule para 3, Companies Act 1967",
    MECHANISM_OPTIONS[3]: "Sixteenth Schedule para 4, Companies Act 1967",
    MECHANISM_OPTIONS[4]: "Sixteenth Schedule para 5, Companies Act 1967",
    MECHANISM_OPTIONS[5]: "Sixteenth Schedule para 8, Companies Act 1967",
    MECHANISM_OPTIONS[6]: "Companies Act 1967 s.386AFA",
    MECHANISM_OPTIONS[7]: "User-specified",
}

# Mechanisms whose claimed basis implies a >=25% holding that should be
# cross-checked against the Register of Members.
PERCENTAGE_BASED_MECHANISMS = {MECHANISM_OPTIONS[0], MECHANISM_OPTIONS[1]}

DIRECT_INDIRECT_OPTIONS = ["Direct", "Indirect"]


def format_mechanisms(mechanism_list, other_text=""):
    """Returns a human-readable string for a list of selected mechanism options."""
    if not mechanism_list:
        return "Not specified"
    parts = []
    for m in mechanism_list:
        if m == "Other":
            parts.append(other_text or "Other (unspecified)")
        else:
            parts.append(m)
    return "; ".join(parts)


# =============================================================================
# RORC EXEMPTION CATEGORIES (Section 6 of PRD)
# =============================================================================
EXEMPTION_CATEGORIES = [
    {"id": "sgx_listed", "label": "Public company listed on SGX",
     "basis": "s.386AA(1) read with 14th Schedule, Companies Act 1967",
     "evidence": "SGX listing printout / Bizfile showing listed status"},
    {"id": "sg_fi", "label": "Singapore financial institution",
     "basis": "14th Schedule para 2, Companies Act 1967",
     "evidence": "MAS Financial Institutions Directory entry or MAS licence confirmation"},
    {"id": "govt_owned", "label": "Wholly owned by Singapore Government",
     "basis": "14th Schedule, Companies Act 1967",
     "evidence": "ACRA business profile confirming government ownership"},
    {"id": "statutory_body", "label": "Wholly owned by a statutory body (public Act, public purpose)",
     "basis": "14th Schedule, Companies Act 1967",
     "evidence": "ACRA business profile; reference to constituting statute"},
    {"id": "wos_exempt_parent", "label": "Wholly-owned subsidiary of an exempt entity above",
     "basis": "14th Schedule read with s.5B, Companies Act 1967",
     "evidence": "ACRA business profile + evidence of 100% ownership by exempt parent"},
    {"id": "foreign_listed", "label": "Listed on a foreign exchange with adequate BO transparency",
     "basis": "14th Schedule para (vi), Companies Act 1967",
     "evidence": "Listing evidence (requires legal confirmation of adequacy - soft stop)"},
    {"id": "sgx_corp_sfa", "label": "SGX-listed corporation (SFA definition)",
     "basis": "s.386AC(c)(iv), Companies Act 1967",
     "evidence": "SGX listing printout"},
    {"id": "llp_own_rorc", "label": "LLP required to maintain its own RORC",
     "basis": "s.386AC(c)(v), Companies Act 1967",
     "evidence": "ACRA business profile showing LLP status (not itself exempt)"},
    {"id": "llp_exempt", "label": "LLP exempt from RORC under 6th Schedule to LLP Act 2005",
     "basis": "s.386AC(c)(vi), Companies Act 1967",
     "evidence": "Evidence of LLP's exempt status"},
    {"id": "trustee", "label": "Trustee of an express trust under Part 7, Trustees Act 1967",
     "basis": "s.386AC(c)(vii), Companies Act 1967",
     "evidence": "Trust deed; evidence trustee acting in that capacity"},
    {"id": "vcc", "label": "Variable Capital Company (VCC)",
     "basis": "s.386AC(c)(viii), Companies Act 1967",
     "evidence": "ACRA business profile showing VCC status"},
    {"id": "none", "label": "None of the above - natural person",
     "basis": "-", "evidence": "-"},
]

EXEMPTION_LABELS = [e["label"] for e in EXEMPTION_CATEGORIES]


# =============================================================================
# RORC ENTRY HELPERS
# =============================================================================
def entry_display_name(e):
    """Returns the controller's name regardless of category."""
    if e["category"] == "corporate":
        return e.get("name") or "Unnamed corporate controller"
    return e.get("full_name") or "Unnamed individual controller"


def entry_key_id(e, idx):
    """A stable-ish unique id for a RORC entry, used as a dict key throughout
    the session state."""
    return f"rorc_{idx}_{entry_display_name(e)}"


# =============================================================================
# CROSS-CHECK: RORC vs REGISTER OF MEMBERS
# =============================================================================
def cross_check_register_of_members(rorc_entries, rom_entries):
    """
    For each RORC entry, try to find a matching name in the Register of
    Members and return its percentage.

    Also identifies Register of Members holders >=25% who do not appear in
    the RORC at all ("unexplained holders").

    Returns:
      rom_match: dict of {rorc_entry_key: {found, percentage, voting_percentage, matched_name}}
      unexplained_holders: list of Register of Members entries >=25% not in RORC
    """
    rom_match = {}
    rorc_names = set()

    for idx, e in enumerate(rorc_entries):
        key = entry_key_id(e, idx)
        name = entry_display_name(e).strip().lower()
        rorc_names.add(name)
        match = next(
            (m for m in rom_entries if m["shareholder_name"].strip().lower() == name),
            None,
        )
        if match:
            rom_match[key] = {
                "found": True,
                "percentage": match.get("percentage_of_total"),
                "voting_percentage": match.get("voting_rights_percentage"),
                "matched_name": match["shareholder_name"],
            }
        else:
            rom_match[key] = {"found": False, "percentage": None, "voting_percentage": None, "matched_name": None}

    unexplained_holders = []
    for m in rom_entries:
        pct = m.get("percentage_of_total")
        name = m["shareholder_name"].strip().lower()
        if pct is not None and pct >= 25 and name not in rorc_names:
            unexplained_holders.append(m)

    return rom_match, unexplained_holders


# =============================================================================
# DISPLAY HELPERS
# =============================================================================
SEVERITY_STYLE = {
    "high": ("🔴", "High priority"),
    "medium": ("🟠", "Needs review"),
    "info": ("🔵", "For your information"),
    "ok": ("🟢", "OK"),
}


def notice_status_flag(status):
    """Maps an annual notice status string to a (severity, label) tuple."""
    return {
        "matched_confirmed": ("ok", "Annual notice provided and confirms controller status"),
        "matched_no_reply": ("medium", "Annual notice provided, but no reply recorded"),
        "matched_not_confirmed": ("medium", "Annual notice reply does not confirm controller status"),
        "wrong_addressee": ("high", "Annual notice addressee does not match this controller"),
        "not_provided": ("high", "No annual notice provided for this controller"),
    }.get(status, ("info", "Unknown"))


def rom_match_flag(rom_match, mechanisms, percentage_based_mechanisms=PERCENTAGE_BASED_MECHANISMS):
    """
    Returns (severity, label) describing how well the Register of Members
    match supports the claimed mechanism(s) of control.

    mechanisms: list of selected mechanism-of-control option strings.
    """
    if mechanisms is None:
        mechanisms = []
    is_pct_mechanism = any(m in percentage_based_mechanisms for m in mechanisms)

    if not rom_match.get("found"):
        if is_pct_mechanism:
            return ("high", "No matching entry in Register of Members - cannot verify claimed shareholding")
        return ("info", "No matching entry in Register of Members (mechanism does not depend on shareholding)")

    pct = rom_match.get("percentage")
    if is_pct_mechanism:
        if pct is not None and pct >= 25:
            return ("ok", f"Register of Members confirms {pct}% - meets >25% threshold")
        else:
            return ("high", f"Register of Members shows only {pct}% - does not meet >25% implied by claimed mechanism")
    else:
        return ("info", f"Register of Members shows {pct}% (mechanism claimed is not percentage-based)")


# =============================================================================
# CROSS-FIELD CONSISTENCY CHECKS (RORC entry vs supporting document)
# =============================================================================
def _normalize(s):
    """Lowercase, strip whitespace, and remove common punctuation for comparison."""
    if s is None:
        return ""
    s = str(s).strip().lower()
    for ch in [",", ".", "-", "  "]:
        s = s.replace(ch, " ")
    return " ".join(s.split())


def _values_conflict(a, b):
    """
    Returns True if a and b appear to be genuinely different (non-empty)
    values, i.e. a likely mismatch worth flagging. Returns False if either
    is empty/unclear/null, or if they match (exactly, or one contains the
    other - to tolerate aliases / partial names / formatting differences).
    """
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return False
    if na in ("unclear", "null", "none", "n/a", "not stated", "not applicable"):
        return False
    if nb in ("unclear", "null", "none", "n/a", "not stated", "not applicable"):
        return False
    if na == nb:
        return False
    if na in nb or nb in na:
        return False
    return True


def cross_field_consistency_check(controller, parsed_doc):
    """
    Compares fields extracted from a supporting document (parsed_doc, the
    dict returned by extract_document for an identity/corporate-profile
    document) against the corresponding fields on the RORC controller
    entry.

    Returns a list of flag dicts, each:
      {"severity": "high"|"info", "field_label": str,
       "rorc_value": ..., "document_value": ..., "message": str}

    An empty list means no conflicts were detected (note: this does NOT
    mean everything is verified - fields that are missing/unclear on
    either side are silently skipped, not treated as a match).
    """
    flags = []
    if not parsed_doc:
        return flags

    if controller["category"] in ("individual", "fallback_director"):
        pairs = [
            ("Full name", controller.get("full_name"), parsed_doc.get("full_name")),
            ("ID / passport number", controller.get("id_number"), parsed_doc.get("nric_number") or parsed_doc.get("passport_number")),
            ("Nationality", controller.get("nationality"), parsed_doc.get("nationality")),
            ("Date of birth", controller.get("date_of_birth"), parsed_doc.get("date_of_birth")),
        ]
    else:  # corporate
        pairs = [
            ("Entity name", controller.get("name"), parsed_doc.get("entity_name")),
            ("UEN / registration number", controller.get("uen") or controller.get("identification_or_registration_number"), parsed_doc.get("registration_number")),
            ("Registered office address", controller.get("registered_office_address"), parsed_doc.get("registered_address")),
            ("Legal form", controller.get("legal_form"), parsed_doc.get("entity_type")),
        ]

    for field_label, rorc_value, doc_value in pairs:
        if _values_conflict(rorc_value, doc_value):
            flags.append({
                "severity": "high",
                "field_label": field_label,
                "rorc_value": rorc_value,
                "document_value": doc_value,
                "message": (
                    f"{field_label} on the uploaded document ('{doc_value}') does not "
                    f"match the RORC entry ('{rorc_value}')."
                ),
            })

    return flags

