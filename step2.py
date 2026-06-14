"""
step2.py
========

Step 2 UI: per-controller verification cards.

Two kinds of cards are shown:

1. RORC controllers (from st.session_state.controllers) - each gets:
   - Annual notice upload (required) -> parsed, checked against this
     controller's name and whether the reply confirms controller status
   - Identity / registration document upload -> parsed, shown as editable
     fields
   - If direct_or_indirect == "Indirect": a chain-tracing section asking
     the user to identify the intermediate entities up to a natural person
     or RORC-exempt entity, with document upload for each link
   - If the Register of Members check flags a mismatch (mechanism implies
     >25% but Register of Members shows less / no match): a text box
     asking for an explanation, plus optional supporting document

2. Unexplained >=25% holders (from st.session_state.unexplained_holders)
   - "Is this shareholder a nominee?" Yes/No
     - Yes -> ask for the RONS / nominee document, identify the nominator,
       then ask "is the nominator the beneficial owner, or someone else?"
       (same branching as the original DBS/Raymond design), then request
       identity documents for whoever is identified. Notes that an annual
       notice should be sent to this person going forward.
     - No -> ask for an explanation (free text) and optionally select an
       exemption category from the dropdown, with supporting document.

All document uploads use the document-type dropdown
(extraction.DOCUMENT_TYPE_OPTIONS), accept PDF/JPG/PNG, and show extracted
fields as EDITABLE inputs so the user can correct misreads (especially for
photographed identity documents).
"""

import streamlit as st

from extraction import (
    get_client, extract_document, DOCUMENT_TYPE_OPTIONS, SUPPORTING_PROMPTS_BY_TYPE,
)
from logic import (
    MECHANISM_OPTIONS, EXEMPTION_CATEGORIES, EXEMPTION_LABELS,
    PERCENTAGE_BASED_MECHANISMS, notice_status_flag, rom_match_flag,
    cross_field_consistency_check,
)
from sgx_listed_companies import check_sgx_listed


# =============================================================================
# GENERIC DOCUMENT UPLOAD + EDITABLE FIELDS WIDGET
# =============================================================================
def document_upload_widget(key_prefix, label="Upload supporting document"):
    """
    Renders a document-type dropdown + file uploader (PDF/JPG/PNG) + parse
    button. After parsing, shows the extracted fields as editable inputs.

    Returns the (possibly user-edited) parsed dict, or None if nothing has
    been parsed yet. The dict is stored in st.session_state under
    f"{key_prefix}_parsed" so it persists across reruns.
    """
    state_key = f"{key_prefix}_parsed"

    doc_type = st.selectbox(
        "Document type", DOCUMENT_TYPE_OPTIONS, key=f"{key_prefix}_doctype"
    )
    uploaded = st.file_uploader(
        label, type=["pdf", "jpg", "jpeg", "png"], key=f"{key_prefix}_file"
    )

    if uploaded and st.button("Parse document", key=f"{key_prefix}_parse_btn"):
        client = get_client()
        prompt = SUPPORTING_PROMPTS_BY_TYPE.get(doc_type, SUPPORTING_PROMPTS_BY_TYPE["Other"])
        with st.spinner("Reading document with Claude..."):
            try:
                result = extract_document(client, prompt, uploaded.read(), uploaded.name)
                result["_filename"] = uploaded.name
                st.session_state[state_key] = result
            except Exception as e:
                st.error(f"Could not parse document: {e}")

    parsed = st.session_state.get(state_key)
    if parsed:
        st.markdown(f"**Extracted from {parsed.get('_filename', 'document')}** "
                     f"({parsed.get('document_subtype', doc_type)}) — please check and correct if needed:")
        edited = {}
        for field, value in parsed.items():
            if field.startswith("_") or field in ("doc_category", "document_subtype"):
                edited[field] = value
                continue
            if isinstance(value, list):
                text_val = st.text_area(field.replace("_", " ").title(), value="; ".join(str(v) for v in value), key=f"{key_prefix}_field_{field}")
                edited[field] = [v.strip() for v in text_val.split(";") if v.strip()]
            else:
                edited[field] = st.text_input(field.replace("_", " ").title(), value="" if value is None else str(value), key=f"{key_prefix}_field_{field}")
        st.session_state[state_key] = edited
        return edited

    return None


# =============================================================================
# RORC CONTROLLER CARD
# =============================================================================
def render_controller_card(c):
    v = c["verification"]

    with st.container(border=True):
        mech_display = c["mechanism"] if c["mechanism"] != "Other" else (c.get("other_mechanism_text") or "Other")
        st.markdown(f"### {c['display_name']} ({c['category'].replace('_', ' ').title()})")
        st.caption(f"Mechanism of control: {mech_display} — {c['direct_or_indirect']}")

        # --- Register of Members check summary ---
        rom_sev, rom_label = rom_match_flag(c["rom_match"], c["mechanism"])
        icon = {"high": "🔴", "medium": "🟠", "info": "🔵", "ok": "🟢"}[rom_sev]
        st.write(f"{icon} **Register of Members check:** {rom_label}")

        # --- 1. Annual notice (required) ---
        st.markdown("#### Annual notice (s.386AG)")
        st.write(f"An annual notice confirming {c['display_name']}'s particulars is required "
                 f"under s.386AIA / s.386AG of the Companies Act 1967.")
        notice_result = document_upload_widget(f"notice_{c['id']}", label="Upload annual notice (PDF/JPG/PNG)")
        if notice_result:
            addressee = (notice_result.get("addressee_name") or "").strip().lower()
            this_name = c["display_name"].strip().lower()
            if addressee and addressee != this_name:
                c["notice_status"] = {"status": "wrong_addressee"}
                st.warning(
                    f"This notice appears to be addressed to '{notice_result.get('addressee_name')}', "
                    f"not '{c['display_name']}'. Please check you've uploaded the correct notice."
                )
            elif notice_result.get("reply_given") is True and notice_result.get("reply_confirms_controller") is True:
                c["notice_status"] = {"status": "matched_confirmed"}
            elif notice_result.get("reply_given") is True:
                c["notice_status"] = {"status": "matched_not_confirmed"}
            else:
                c["notice_status"] = {"status": "matched_no_reply"}
            v["annual_notice"] = notice_result
        notice_sev, notice_label = notice_status_flag(c["notice_status"].get("status"))
        icon = {"high": "🔴", "medium": "🟠", "info": "🔵", "ok": "🟢"}[notice_sev]
        st.write(f"{icon} {notice_label}")

        # --- 2. Identity / registration document ---
        st.markdown("#### Identity / registration verification")
        if c["category"] == "corporate":
            st.write(f"Please upload a document verifying: name **{c.get('name')}**, "
                     f"UEN **{c.get('uen') or 'not stated'}**, registered office "
                     f"**{c.get('registered_office_address') or 'not stated'}**.")
        else:
            st.write(f"Please upload a document verifying: name **{c['display_name']}**, "
                     f"ID number **{c.get('id_number') or 'not stated'}**, "
                     f"nationality **{c.get('nationality') or 'not stated'}**.")
        identity_result = document_upload_widget(f"identity_{c['id']}", label="Upload identity / registration document (PDF/JPG/PNG)")
        if identity_result:
            v["identity_doc"] = identity_result

            consistency_flags = cross_field_consistency_check(c, identity_result)
            v["consistency_flags"] = consistency_flags
            if consistency_flags:
                for cf in consistency_flags:
                    st.error(f"🔴 {cf['message']}")
                st.caption(
                    "Please check whether this is a data entry error in the RORC, an "
                    "error in the uploaded document, or evidence that the RORC entry "
                    "needs to be corrected."
                )
            else:
                st.success("✅ No conflicts detected between this document and the RORC entry "
                            "(for the fields that could be compared).")

        # --- 3. Indirect chain tracing ---
        if c["direct_or_indirect"] == "Indirect":
            st.markdown("#### Trace indirect control")
            st.write(
                f"{c['display_name']}'s control is recorded as indirect. Please identify "
                f"the chain of intermediate entities up to a natural person or a "
                f"recognised RORC-exempt entity."
            )
            chain = v.get("chain", [])
            n = st.number_input(
                "Number of entities in the chain (including the natural person / exempt entity at the top)",
                min_value=1, max_value=6, value=max(1, len(chain)), key=f"chainN_{c['id']}",
            )
            new_chain = []
            for i in range(int(n)):
                st.markdown(f"**Chain entity {i+1}**")
                existing = chain[i] if i < len(chain) else {}
                col1, col2 = st.columns(2)
                with col1:
                    ename = st.text_input("Name", value=existing.get("name", ""), key=f"chain_name_{c['id']}_{i}")
                with col2:
                    etype = st.selectbox("Type", ["individual", "corporate"],
                                          index=0 if existing.get("type", "individual") == "individual" else 1,
                                          key=f"chain_type_{c['id']}_{i}")
                exemption = existing.get("exemption")
                if etype == "corporate":
                    exemption_label = st.selectbox(
                        "Exemption category (if this is the top of the chain)",
                        EXEMPTION_LABELS,
                        index=EXEMPTION_LABELS.index(exemption["label"]) if exemption and exemption.get("label") in EXEMPTION_LABELS else len(EXEMPTION_LABELS) - 1,
                        key=f"chain_exempt_{c['id']}_{i}",
                    )
                    exemption = next(e for e in EXEMPTION_CATEGORIES if e["label"] == exemption_label)
                else:
                    exemption = None

                doc_result = document_upload_widget(f"chain_doc_{c['id']}_{i}", label=f"Upload supporting document for {ename or 'this entity'} (PDF/JPG/PNG)")

                new_chain.append({"name": ename, "type": etype, "exemption": exemption, "document": doc_result})

            v["chain"] = new_chain

            top = new_chain[-1] if new_chain else None
            if top and top["type"] == "individual":
                v["chain_termination"] = f"Chain terminates at natural person: {top['name']}"
            elif top and top["type"] == "corporate" and top.get("exemption") and top["exemption"]["id"] != "none":
                v["chain_termination"] = (
                    f"Chain terminates at {top['name']} — exemption category "
                    f"'{top['exemption']['label']}' ({top['exemption']['basis']}). "
                    f"Evidence required: {top['exemption']['evidence']}."
                )
                if top["exemption"]["id"] in ("sgx_listed", "sgx_corp_sfa"):
                    sgx_check = check_sgx_listed(top["name"])
                    if sgx_check["matched"]:
                        st.success(
                            f"✅ '{top['name']}' matches '{sgx_check['matched_name']}' in the "
                            f"bundled SGX-listed companies reference list — supports the "
                            f"SGX-listed exemption claim."
                        )
                    else:
                        st.warning(
                            f"⚠ '{top['name']}' was not found in the bundled SGX-listed "
                            f"companies reference list. This list is indicative only (data "
                            f"as of ~2020) and may be incomplete or outdated — please "
                            f"upload an SGX listing printout or current Bizfile extract as "
                            f"evidence regardless."
                        )
                if top["exemption"]["id"] == "foreign_listed":
                    st.warning(
                        "Note: the adequacy of a foreign exchange's BO transparency "
                        "requirements is a legal question. This tool flags the chain "
                        "as terminating here but recommends confirming adequacy with "
                        "legal counsel."
                    )
            else:
                v["chain_termination"] = None
                st.info("The top of the chain is a corporate entity with no exemption selected — "
                        "tracing may need to continue further.")

            if v.get("chain_termination"):
                st.success(v["chain_termination"])

        # --- 4. Register of Members mismatch explanation ---
        if rom_sev == "high":
            st.markdown("#### Explain discrepancy with Register of Members")
            rom = c["rom_match"]
            if not rom["found"]:
                st.write(
                    f"{c['display_name']} is recorded with mechanism '{mech_display}', but no "
                    f"matching entry was found in the Register of Members. Please explain — "
                    f"e.g. shares are held under a different name (nominee/trustee/related "
                    f"entity), or this is a different basis of control."
                )
            else:
                st.write(
                    f"The Register of Members shows {rom['matched_name']} holds "
                    f"{rom['percentage']}%, but the mechanism '{mech_display}' implies >25%. "
                    f"Please explain — e.g. additional interest via joint arrangement or "
                    f"voting agreement."
                )
            v["mismatch_explanation"] = st.text_area(
                "Explanation", value=v.get("mismatch_explanation", ""), key=f"mismatch_{c['id']}"
            )
            mismatch_doc = document_upload_widget(f"mismatch_doc_{c['id']}", label="Upload supporting document for this explanation (optional, PDF/JPG/PNG)")
            if mismatch_doc:
                v["mismatch_doc"] = mismatch_doc

        # --- Resolved checkbox ---
        v["resolved"] = st.checkbox(
            "Mark this controller's verification as resolved",
            value=v.get("resolved", False), key=f"resolved_{c['id']}",
        )


# =============================================================================
# UNEXPLAINED >=25% HOLDER CARD
# =============================================================================
def render_unexplained_holder_card(h, idx):
    inv = h["investigation"]

    with st.container(border=True):
        st.markdown(f"### {h['shareholder_name']} ({h['percentage_of_total']}% — not in RORC)")
        st.write(
            f"**{h['shareholder_name']}** holds {h['percentage_of_total']}% of shares per "
            f"the Register of Members, which meets the >25% significant interest threshold "
            f"(Sixteenth Schedule, Companies Act 1967), but does not appear in the RORC."
        )

        is_nominee = st.radio(
            f"Is {h['shareholder_name']} holding these shares as a nominee for someone else?",
            options=["Yes", "No"],
            index=0 if inv.get("is_nominee") is True else (1 if inv.get("is_nominee") is False else None),
            key=f"nominee_{idx}",
        )
        inv["is_nominee"] = (is_nominee == "Yes")

        if is_nominee == "Yes":
            st.markdown("#### Nominee shareholder details")
            st.write(
                f"Please upload the Register of Nominee Shareholders (RONS) entry or "
                f"other document evidencing the nominee arrangement for "
                f"{h['shareholder_name']}."
            )
            nominee_doc = document_upload_widget(f"nominee_doc_{idx}", label="Upload nominee document (PDF/JPG/PNG)")
            if nominee_doc:
                inv["nominee_doc"] = nominee_doc
                inv["nominator_name"] = nominee_doc.get("nominator_name", inv.get("nominator_name", ""))

            inv["nominator_name"] = st.text_input(
                "Nominator (the person/entity on whose behalf the shares are held)",
                value=inv.get("nominator_name", ""), key=f"nominator_name_{idx}",
            )

            if inv["nominator_name"]:
                st.markdown("#### Clarifying question")
                answer = st.radio(
                    f"Is **{inv['nominator_name']}** the beneficial owner of this "
                    f"{h['percentage_of_total']}% interest (i.e. does {inv['nominator_name']} "
                    f"ultimately benefit from and/or control these shares), or does "
                    f"{inv['nominator_name']} hold them on behalf of someone else?",
                    options=[f"Yes — {inv['nominator_name']} is the beneficial owner",
                             "No — someone else is the beneficial owner"],
                    index=None, key=f"benowner_{idx}",
                )
                if answer and answer.startswith("Yes"):
                    inv["beneficial_owner_name"] = inv["nominator_name"]
                elif answer and answer.startswith("No"):
                    inv["beneficial_owner_name"] = st.text_input(
                        f"Who is the actual beneficial owner of the {h['percentage_of_total']}% "
                        f"interest held via {h['shareholder_name']}?",
                        value=inv.get("beneficial_owner_name", ""), key=f"actual_bo_{idx}",
                    )
                    if inv["beneficial_owner_name"]:
                        st.warning(
                            f"Noted: the nominee document names {inv['nominator_name']} as "
                            f"nominator, but {inv['beneficial_owner_name']} has been identified "
                            f"as the actual beneficial owner. This discrepancy should be "
                            f"explained in the written submission to ACRA."
                        )

            if inv.get("beneficial_owner_name"):
                st.markdown(f"#### Identity verification for {inv['beneficial_owner_name']}")
                identity_doc = document_upload_widget(f"bo_identity_{idx}", label=f"Upload identity document for {inv['beneficial_owner_name']} (PDF/JPG/PNG)")
                if identity_doc:
                    inv["identity_doc"] = identity_doc
                st.info(
                    f"Note: {inv['beneficial_owner_name']} appears to meet the >25% "
                    f"significant interest threshold and should be added to the RORC. "
                    f"An annual notice should be sent to {inv['beneficial_owner_name']} "
                    f"going forward, per s.386AIA."
                )

        elif is_nominee == "No":
            st.markdown("#### Explanation")
            inv["resolution_text"] = st.text_area(
                f"Please explain why {h['shareholder_name']} ({h['percentage_of_total']}%) "
                f"is not in the RORC — e.g. RORC-exemption category, or this is an "
                f"oversight to be corrected.",
                value=inv.get("resolution_text", ""), key=f"explain_{idx}",
            )

            claim_exemption = st.checkbox("This entity falls within a RORC exemption category", key=f"claim_exempt_{idx}", value=inv.get("exemption") is not None)
            if claim_exemption:
                exemption_label = st.selectbox(
                    "Exemption category", EXEMPTION_LABELS,
                    index=EXEMPTION_LABELS.index(inv["exemption"]["label"]) if inv.get("exemption") and inv["exemption"].get("label") in EXEMPTION_LABELS else 0,
                    key=f"exempt_select_{idx}",
                )
                inv["exemption"] = next(e for e in EXEMPTION_CATEGORIES if e["label"] == exemption_label)
                st.caption(f"Legal basis: {inv['exemption']['basis']}. Evidence required: {inv['exemption']['evidence']}")

                if inv["exemption"]["id"] in ("sgx_listed", "sgx_corp_sfa"):
                    sgx_check = check_sgx_listed(h["shareholder_name"])
                    if sgx_check["matched"]:
                        st.success(
                            f"✅ '{h['shareholder_name']}' matches '{sgx_check['matched_name']}' "
                            f"in the bundled SGX-listed companies reference list — supports "
                            f"the SGX-listed exemption claim."
                        )
                    else:
                        st.warning(
                            f"⚠ '{h['shareholder_name']}' was not found in the bundled "
                            f"SGX-listed companies reference list. This list is indicative "
                            f"only (data as of ~2020) and may be incomplete or outdated — "
                            f"please upload an SGX listing printout or current Bizfile "
                            f"extract as evidence regardless."
                        )

                exempt_doc = document_upload_widget(f"exempt_doc_{idx}", label="Upload evidence of exemption (PDF/JPG/PNG)")
                if exempt_doc:
                    inv["exemption_doc"] = exempt_doc
            else:
                inv["exemption"] = None

        if is_nominee is not None:
            inv["resolved"] = st.checkbox(
                "Mark this item as resolved", value=inv.get("resolved", False), key=f"resolved_holder_{idx}",
            )


# =============================================================================
# MAIN RENDER
# =============================================================================
def render():
    st.title("Step 2 — Verification")
    st.markdown(
        "Each confirmed registrable controller, and each unexplained ≥25% "
        "shareholder, has its own verification card below. Please complete "
        "each one and mark it as resolved when done."
    )

    controllers = st.session_state.controllers
    unexplained_holders = st.session_state.unexplained_holders

    if controllers:
        st.markdown("## Registrable controllers")
        for c in controllers:
            render_controller_card(c)

    if unexplained_holders:
        st.markdown("## Shareholders ≥25% not in RORC")
        for idx, h in enumerate(unexplained_holders):
            render_unexplained_holder_card(h, idx)

    if not controllers and not unexplained_holders:
        st.info("No controllers or unexplained holders to verify.")

    st.markdown("---")
    if st.button("Proceed to Step 3 — Summary & report ➡", type="primary"):
        st.session_state.stage = 3
        st.rerun()
