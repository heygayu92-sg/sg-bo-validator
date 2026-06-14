"""
step1.py
========

Step 1 UI: RORC + Register of Members upload, parsing, cross-check,
mechanism-of-control / direct-indirect dropdowns, and an explicit
confirmation screen listing the final registrable controllers before
proceeding to Step 2.

Populates st.session_state.controllers and
st.session_state.unexplained_holders, which Step 2 consumes.
"""

import streamlit as st

from extraction import get_client, extract_document, RORC_PROMPT, ROM_PROMPT
from logic import (
    MECHANISM_OPTIONS, MECHANISM_RULE_BASIS, DIRECT_INDIRECT_OPTIONS,
    entry_display_name, entry_key_id, cross_check_register_of_members,
    format_mechanisms,
)


def _init_controller(e, idx, rom_match):
    """Build the working controller dict for one RORC entry."""
    cid = entry_key_id(e, idx)
    return {
        "id": cid,
        "category": e["category"],
        "display_name": entry_display_name(e),
        **e,
        "rom_match": rom_match,
        "mechanism": [],
        "other_mechanism_text": "",
        "direct_or_indirect": None,
        "notice_status": {"status": "not_provided"},  # updated in Step 2
        "verification": {"resolved": False},
    }


def render():
    st.title("Step 1 — RORC & Register of Members")
    st.markdown(
        "Upload the **Register of Registrable Controllers (RORC)** and the "
        "**Register of Members**. Both are required. The AI will extract "
        "the key details and cross-check the RORC against the Register of "
        "Members."
    )

    c1, c2 = st.columns(2)
    with c1:
        st.session_state.company_name = st.text_input("Company name", value=st.session_state.company_name)
    with c2:
        st.session_state.company_uen = st.text_input("UEN (optional)", value=st.session_state.company_uen)

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        rorc_file = st.file_uploader("RORC (PDF)", type=["pdf"], key="upload_rorc")
    with col2:
        rom_file = st.file_uploader("Register of Members (PDF)", type=["pdf"], key="upload_rom")

    st.markdown("---")

    if st.button("Parse documents", type="primary"):
        if rorc_file is None or rom_file is None:
            st.warning("Please upload both the RORC and the Register of Members.")
        else:
            client = get_client()
            with st.spinner("Reading documents with Claude..."):
                try:
                    st.session_state.extracted["RORC"] = extract_document(client, RORC_PROMPT, rorc_file.read(), rorc_file.name)
                except Exception as e:
                    st.error(f"Could not parse RORC: {e}")
                try:
                    st.session_state.extracted["Register of Members"] = extract_document(client, ROM_PROMPT, rom_file.read(), rom_file.name)
                except Exception as e:
                    st.error(f"Could not parse Register of Members: {e}")
            st.session_state.controllers = []
            st.session_state.step1_confirmed = False
            st.success("Documents parsed. Please review below.")

    if "RORC" not in st.session_state.extracted or "Register of Members" not in st.session_state.extracted:
        return

    # ---- Review extracted data ----
    st.markdown("## Review extracted information")

    rorc_data = st.session_state.extracted["RORC"]
    with st.expander(f"📄 RORC — {rorc_data.get('company_name', 'Unknown company')}", expanded=True):
        entries = rorc_data.get("entries", [])
        if entries:
            rows = [{
                "Name": entry_display_name(e),
                "Category": e["category"],
                "Nature of control (as stated)": e.get("nature_of_control"),
                "% (as stated)": e.get("percentage"),
                "Confirmed?": e.get("confirmed"),
            } for e in entries]
            st.dataframe(rows, use_container_width=True)
            with st.expander("Show full extracted fields (per ACRA RORC field set)"):
                st.json(entries)
        else:
            st.info("No entries found.")
        st.session_state.confirmed["RORC"] = st.checkbox("I confirm this is an accurate reading of the RORC", key="confirm_RORC")

    rom_data = st.session_state.extracted["Register of Members"]
    with st.expander(f"📄 Register of Members — {rom_data.get('company_name', 'Unknown company')}", expanded=True):
        st.dataframe(rom_data.get("entries", []), use_container_width=True)
        st.session_state.confirmed["Register of Members"] = st.checkbox("I confirm this is an accurate reading of the Register of Members", key="confirm_ROM")

    if not (st.session_state.confirmed.get("RORC") and st.session_state.confirmed.get("Register of Members")):
        st.caption("Please confirm both documents above to continue.")
        return

    # ---- Build controllers (once) ----
    rorc_entries = rorc_data.get("entries", [])
    rom_entries = rom_data.get("entries", [])

    if not st.session_state.controllers:
        rom_matches, unexplained_holders = cross_check_register_of_members(rorc_entries, rom_entries)
        st.session_state.controllers = [
            _init_controller(e, idx, rom_matches.get(entry_key_id(e, idx)))
            for idx, e in enumerate(rorc_entries)
        ]
        st.session_state.unexplained_holders = [
            {**h, "investigation": {"resolved": False, "is_nominee": None}}
            for h in unexplained_holders
        ]

    controllers = st.session_state.controllers
    unexplained_holders = st.session_state.unexplained_holders

    # ---- Cross-check display + dropdowns ----
    st.markdown("## RORC entries — cross-check & classification")
    st.caption(
        "For each RORC entry, review the Register of Members cross-check and select "
        "the mechanism of control and whether it is held directly or indirectly."
    )

    for c in controllers:
        with st.container(border=True):
            st.markdown(f"### {c['display_name']} ({c['category'].replace('_', ' ').title()})")

            rom = c["rom_match"]
            if rom["found"]:
                st.write(f"**Register of Members:** {rom['matched_name']} holds **{rom['percentage']}%** "
                         f"(voting: {rom['voting_percentage']}%)")
                if rom["percentage"] is not None and rom["percentage"] >= 25:
                    st.success("Meets the >25% significant interest threshold per the Register of Members.")
                else:
                    st.warning("Below 25% per the Register of Members. If the mechanism selected below "
                                "implies >25%, this will be raised for explanation in Step 2.")
            else:
                st.write("**Register of Members:** No matching entry found.")
                st.warning("Could not match this controller to a shareholder in the Register of Members.")

            st.markdown("**User classification**")
            colC, colD = st.columns(2)
            with colC:
                st.write("Mechanism(s) of control (select all that apply):")
                if not isinstance(c.get("mechanism"), list):
                    c["mechanism"] = []
                selected = []
                for opt in MECHANISM_OPTIONS:
                    checked = st.checkbox(
                        opt, value=opt in c["mechanism"], key=f"mech_{c['id']}_{opt}",
                    )
                    if checked:
                        selected.append(opt)
                        if opt != "Other":
                            st.caption(f"&nbsp;&nbsp;&nbsp;&nbsp;Legal basis: {MECHANISM_RULE_BASIS.get(opt, '-')}")
                c["mechanism"] = selected
                if "Other" in selected:
                    c["other_mechanism_text"] = st.text_input(
                        "Please specify the other mechanism of control",
                        key=f"mech_other_{c['id']}", value=c.get("other_mechanism_text", ""),
                    )
            with colD:
                if MECHANISM_OPTIONS[6] in c["mechanism"]:  # fallback director selected
                    c["direct_or_indirect"] = "Not applicable"
                    st.selectbox("Direct / Indirect", options=["Not applicable"], key=f"dir_{c['id']}", disabled=True)
                else:
                    dio = st.selectbox(
                        "Direct or indirect control?",
                        options=DIRECT_INDIRECT_OPTIONS,
                        key=f"dir_{c['id']}",
                        index=DIRECT_INDIRECT_OPTIONS.index(c["direct_or_indirect"]) if c["direct_or_indirect"] in DIRECT_INDIRECT_OPTIONS else 0,
                    )
                    c["direct_or_indirect"] = dio

    if unexplained_holders:
        st.markdown("## ⚠ Shareholders above 25% not found in RORC")
        for h in unexplained_holders:
            st.error(
                f"**{h['shareholder_name']}** holds {h['percentage_of_total']}% of shares "
                f"per the Register of Members but does not appear in the RORC. This will "
                f"become its own item to investigate in Step 2."
            )

    # ---- All checkboxes/dropdowns set? ----
    all_set = all(
        c["mechanism"] and (c["direct_or_indirect"] or MECHANISM_OPTIONS[6] in c["mechanism"])
        for c in controllers
    )
    if not all_set:
        st.caption("Please select at least one mechanism of control (and direct/indirect, where applicable) for every controller above.")
        return

    # ---- Confirmation screen ----
    st.markdown("---")
    st.markdown("## Confirm registrable controllers to verify")
    st.caption(
        "Please review the list below. These are the controllers (and any "
        "unexplained >=25% shareholders) that will be carried into Step 2 "
        "for individual verification."
    )

    for c in controllers:
        mech = format_mechanisms(c["mechanism"], c.get("other_mechanism_text", ""))
        st.write(f"- **{c['display_name']}** ({c['category'].replace('_', ' ').title()}) — {mech}, "
                 f"{c['direct_or_indirect']}")
    for h in unexplained_holders:
        st.write(f"- **{h['shareholder_name']}** ({h['percentage_of_total']}% per Register of Members, "
                 f"not in RORC) — to be investigated")

    confirm = st.checkbox("I confirm this is the correct list of registrable controllers and items to verify", key="step1_confirm_checkbox")

    if st.button("Proceed to Step 2 — Verification ➡", type="primary", disabled=not confirm):
        st.session_state.step1_confirmed = True
        st.session_state.stage = 2
        st.rerun()
