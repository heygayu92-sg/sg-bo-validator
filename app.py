"""
app.py
======

Main entry point for the SG BO Validator Streamlit app.

Responsibilities:
  - Page configuration
  - Session state initialisation
  - Sidebar (progress indicator, privacy notice, restart button)
  - Routing between Step 1 / Step 2 / Step 3

The actual step UIs live in step1.py, step2.py, step3.py. Business logic
is in logic.py, document extraction in extraction.py, and PDF report
generation in report.py.

This is a prototype for demonstration purposes only. It is not legal
advice.
"""

import streamlit as st

import step1
import step2
import step3


st.set_page_config(page_title="SG BO Validator", page_icon="🔎", layout="wide")


# =============================================================================
# SESSION STATE INIT
# =============================================================================
DEFAULTS = {
    "stage": 1,
    "extracted": {},          # raw RORC / Register of Members extraction
    "confirmed": {},           # confirmation checkboxes for Step 1 documents
    "controllers": [],          # list of controller dicts (built in Step 1, used in Steps 2-3)
    "unexplained_holders": [],   # list of >=25% Register of Members holders not in RORC
    "company_name": "",
    "company_uen": "",
    "step1_confirmed": False,
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# =============================================================================
# SIDEBAR
# =============================================================================
with st.sidebar:
    st.title("🔎 SG BO Validator")
    st.caption("Prototype — RORC focus")
    st.markdown("---")

    stage_labels = {
        1: "1. RORC & Register of Members",
        2: "2. Per-controller verification",
        3: "3. Summary & report",
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
        "Nothing is stored server-side."
    )
    st.markdown("---")
    st.caption("Prototype for internal demo purposes only. Not legal advice.")

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
# ROUTER
# =============================================================================
if st.session_state.stage == 1:
    step1.render()
elif st.session_state.stage == 2:
    step2.render()
elif st.session_state.stage == 3:
    step3.render()
