"""
step3.py
========

Step 3 UI: summary of all controllers and unexplained holders, resolved vs
outstanding items, and the downloadable PDF validation report.
"""

import streamlit as st

from logic import notice_status_flag, rom_match_flag
from report import generate_report_pdf


def render():
    st.title("Step 3 — Summary & Validation Report")

    controllers = st.session_state.controllers
    unexplained_holders = st.session_state.unexplained_holders

    st.markdown("## Registrable controllers")
    for c in controllers:
        with st.container(border=True):
            st.markdown(f"#### {c['display_name']} ({c['category'].replace('_', ' ').title()})")
            mech = c.get("mechanism") or "Not specified"
            if mech == "Other":
                mech = c.get("other_mechanism_text") or "Other (unspecified)"
            st.write(f"**Mechanism of control:** {mech}")
            st.write(f"**Direct / Indirect:** {c.get('direct_or_indirect', 'Not specified')}")

            rom_sev, rom_label = rom_match_flag(c["rom_match"], c["mechanism"])
            icon = {"high": "🔴", "medium": "🟠", "info": "🔵", "ok": "🟢"}[rom_sev]
            st.write(f"**Register of Members:** {icon} {rom_label}")

            notice_sev, notice_label = notice_status_flag(c["notice_status"].get("status"))
            icon = {"high": "🔴", "medium": "🟠", "info": "🔵", "ok": "🟢"}[notice_sev]
            st.write(f"**Annual notice:** {icon} {notice_label}")

            v = c["verification"]
            if v.get("chain_termination"):
                st.success(v["chain_termination"])
            if v.get("mismatch_explanation"):
                st.write(f"**Discrepancy explanation:** {v['mismatch_explanation']}")

            status = "✅ Resolved" if v.get("resolved") else "🔴 Outstanding"
            st.write(f"**Verification status:** {status}")

    if unexplained_holders:
        st.markdown("---")
        st.markdown("## Shareholders ≥25% not in RORC")
        for h in unexplained_holders:
            with st.container(border=True):
                st.markdown(f"#### {h['shareholder_name']} ({h['percentage_of_total']}%)")
                inv = h["investigation"]
                if inv.get("is_nominee") is True:
                    st.write(f"**Nominee shareholder** — nominator: {inv.get('nominator_name', '-')}")
                    if inv.get("beneficial_owner_name"):
                        st.write(f"**Identified beneficial owner:** {inv['beneficial_owner_name']}")
                        st.info("An annual notice should be sent to this person going forward (s.386AIA).")
                elif inv.get("is_nominee") is False:
                    st.write(f"**Not a nominee.** Explanation: {inv.get('resolution_text', '-')}")
                    if inv.get("exemption"):
                        st.write(f"**Exemption claimed:** {inv['exemption']['label']}")
                else:
                    st.write("Not yet investigated.")

                status = "✅ Resolved" if inv.get("resolved") else "🔴 Outstanding"
                st.write(f"**Status:** {status}")

    st.markdown("---")
    st.markdown("## Overall gap summary")
    unresolved_controllers = [c for c in controllers if not c["verification"].get("resolved")]
    unresolved_holders = [h for h in unexplained_holders if not h["investigation"].get("resolved")]

    if unresolved_controllers or unresolved_holders:
        for c in unresolved_controllers:
            st.error(f"**{c['display_name']}**: verification not yet resolved.")
        for h in unresolved_holders:
            st.error(f"**{h['shareholder_name']}** ({h['percentage_of_total']}%): investigation not yet resolved.")
    else:
        st.success("All items have been marked as resolved.")

    st.markdown("---")
    st.markdown("## Download validation report")
    st.caption(
        "This report summarises the controller-by-controller verification and is "
        "structured to serve as the written explanation accompanying supporting "
        "documents submitted to ACRA."
    )

    if st.button("Generate report", type="primary"):
        pdf_buf = generate_report_pdf(
            st.session_state.company_name or "Unnamed Company",
            st.session_state.company_uen,
            controllers, unexplained_holders,
        )
        st.session_state["report_pdf"] = pdf_buf.getvalue()
        st.success("Report generated.")

    if "report_pdf" in st.session_state:
        st.download_button(
            "⬇ Download validation report (PDF)",
            data=st.session_state["report_pdf"],
            file_name=f"{(st.session_state.company_name or 'company').replace(' ', '_')}_RORC_validation_report.pdf",
            mime="application/pdf",
        )
