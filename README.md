# SG BO Validator — Full Prototype (Stages 1-3)

A single-file Streamlit app that walks through:

- **Stage 1** — upload RORC, ROND, RONS, Register of Members; AI parses
  each; you confirm; first-cut cross-check runs and flags issues.
- **Stage 2** — for each candidate controller, answer clarifying
  questions (e.g. the nominee/beneficial-owner question), upload
  supporting documents, AI parses them, and check exemption/tracing
  status for corporate controllers.
- **Stage 3** — view the assembled ownership chain, see the gap summary,
  and download a PDF validation report.

---

## How to update your existing Streamlit app

If you've already deployed the Stage 1 version from before, you just need
to **replace `app.py`** with the new one in this folder — everything else
(`requirements.txt`, secrets) stays the same.

1. Go to your GitHub repo (`sg-bo-validator`).
2. Click on `app.py` → click the pencil (✏️ edit) icon.
3. Select all the existing content and delete it.
4. Open the new `app.py` from this folder, copy all of it, and paste it in.
5. Click **Commit changes**.
6. Streamlit Cloud will automatically redeploy (takes ~1 minute). If it
   doesn't, go to your app on share.streamlit.io and click **Reboot app**.

---

## If starting fresh

Follow the same GitHub + Streamlit + secrets steps as the Stage 1 README:

1. Create a GitHub repo, upload `app.py` and `requirements.txt`.
2. Deploy on share.streamlit.io, pointing to `app.py`.
3. Add your Anthropic API key under the app's **Settings → Secrets**:
   ```
   ANTHROPIC_API_KEY = "sk-ant-your-actual-key-here"
   ```

---

## Demo walkthrough — "Acme Holdings Pte Ltd"

### Stage 1

Upload these four files (from `sample_docs/`):

| Upload slot | File |
|---|---|
| RORC | `01_RORC.pdf` |
| ROND | `02_ROND.pdf` |
| RONS | `03_RONS.pdf` |
| Register of Members | `04_Register_of_Members.pdf` |

Click **Parse documents**, confirm each one, then **Run first-cut
cross-check**. You should see 4 flags:

1. 🔵 Info — John Tan appears in both RORC and ROND
2. 🔴 High — DBS Nominees holds 25% as nominee; Raymond Koh (the
   RONS-named nominator) isn't in the RORC
3. 🟠 Medium — Meridian Capital Pte Ltd is a corporate controller
   requiring tracing
4. 🟠 Medium — John Tan's RORC particulars are unconfirmed

Click **Proceed to Stage 2**.

### Stage 2

You'll see a card for each candidate controller:

- **Tan Wei Ming** — individual, source RORC. Upload any NRIC-style PDF
  (or reuse `07_Raymond_Koh_NRIC.pdf` for demo purposes — the AI will read
  whatever you give it).

- **Meridian Capital Pte Ltd** — corporate, source RORC. This card asks
  you to select an exemption category or trace further:
  - Select **"None of the above — not exempt"**.
  - Add the traced entity: name `Sarah Lim`, type `individual`,
    percentage `100`.
  - Upload `05_Meridian_Capital_Bizfile.pdf` for Meridian Capital itself.
  - A new card appears for **Sarah Lim** — upload
    `06_Sarah_Lim_Passport.pdf` for her.

- **John Tan** — individual, source RORC. Upload any sample identity PDF.

- **Raymond Koh** — this is the RONS-nominator candidate. You'll see the
  **clarifying question**:
  *"Is Raymond Koh the beneficial owner of this 25% interest, or does he
  hold them on behalf of someone else?"*
  - Choose **"Yes — Raymond Koh is the beneficial owner"**.
  - Upload `07_Raymond_Koh_NRIC.pdf`.

  To see the alternative branch, you can instead choose **"No"** and type
  in a different name — the app will record this as a discrepancy to
  explain in the report.

Click **Proceed to Stage 3**.

### Stage 3

You'll see the assembled chain with each node's mechanism of control,
documents, and status. Click **Generate report**, then **Download
validation report (PDF)** to get the final report — this is the
ACRA-ready document.

---

## Notes for your boss demo

- The clarifying yes/no question for Raymond Koh is the key "evidence,
  not declaration" moment — it shows the tool isn't just trusting the
  RONS at face value.
- The Meridian Capital → Sarah Lim trace demonstrates the all-corporate
  tracing requirement (s.386AC) in action.
- The final PDF report is structured to double as the written explanation
  ACRA expects alongside supporting documents.

## What's still a prototype simplification

- Exemption category selection and tracing are manual (user selects/types
  rather than the AI inferring them from documents) — this keeps Stage 2
  predictable for a demo. A production version could have the AI suggest
  the exemption category based on parsed Bizfile data.
- No login/session persistence — by design (single-session, per the PRD).
- Validation status logic is rule-based and simple; production version
  would have more nuanced checks (e.g. cross-referencing parsed document
  fields against claimed percentages).
