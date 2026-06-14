# SG BO Validator — v4 (multi-file, per-controller verification)

This version splits the app into multiple files for easier editing, and
restructures the flow so:

- **Step 1** only collects the RORC and Register of Members, runs the
  cross-check, and lets you classify each controller (mechanism of
  control + direct/indirect) before an explicit **confirmation screen**.
- **Step 2** verifies each registrable controller **one at a time**,
  including its own required annual notice — and separately handles any
  ≥25% shareholders from the Register of Members who aren't in the RORC
  (asking whether they're a nominee, tracing to a beneficial owner if so,
  or asking for an exemption/oversight explanation if not).
- **Step 3** is unchanged in spirit: summary + downloadable PDF report.

---

## File structure

| File | Purpose |
|---|---|
| `app.py` | Main entry point. Page config, session state setup, sidebar (progress + restart), and routing to Step 1/2/3. |
| `extraction.py` | Everything related to the Anthropic API: the Claude client, all extraction prompts (RORC, Register of Members, Annual Notice, NRIC, Passport, Corporate Profile, Nominee document, Trust deed, Other), the document-type dropdown options, and `extract_document()` which routes PDF/JPG/PNG to the right API call. |
| `logic.py` | Pure business logic, no UI: mechanism-of-control options and their legal basis, the 11 RORC exemption categories, the RORC ↔ Register of Members cross-check, **cross-field consistency checks** (RORC entry vs uploaded supporting document), and helper functions for displaying status flags. Can be tested independently of Streamlit. |
| `sgx_listed_companies.py` | A bundled, offline reference list of ~466 SGX-listed company names (indicative, dated ~2020), plus `check_sgx_listed()` for a name-matching check used when a user claims the SGX-listed exemption category. |
| `report.py` | Builds the downloadable PDF validation report from the final controller/holder data, using reportlab. Includes any cross-field consistency flags. |
| `step1.py` | Step 1 UI: upload RORC + Register of Members, review extracted data, cross-check display, mechanism/direct-indirect dropdowns, and the confirmation screen. |
| `step2.py` | Step 2 UI: one verification card per registrable controller (annual notice, identity doc + cross-field consistency check, indirect chain tracing with SGX check, Register of Members mismatch explanation) and one card per unexplained ≥25% holder (nominee Yes/No branching, with SGX check on exemption claims). |
| `step3.py` | Step 3 UI: summary of all controllers/holders, resolved vs outstanding items, and the report download button. |

---

## Deploying / updating on GitHub + Streamlit

Since this is now **multiple files**, you'll upload all of them to your
GitHub repo (not just `app.py`).

### If updating your existing repo

1. Go to your GitHub repo (`sg-bo-validator`)
2. For `app.py`, `requirements.txt`, `logic.py`, `report.py`, `step2.py`:
   click the file → edit (✏️) → select all → delete → paste the new
   content → Commit (these have changed in this update)
3. For the **new file** `sgx_listed_companies.py`: click **Add file →
   Create new file**, type the filename exactly, paste the content, and
   click **Commit changes**.
4. Streamlit will auto-redeploy once all files are committed. If it
   doesn't, go to your app on share.streamlit.io and click **Reboot app**.

### If starting fresh

1. Create a GitHub repo, upload all 8 `.py` files and `requirements.txt`
   (all in the root of the repo, no subfolders)
2. Deploy on share.streamlit.io, with **Main file path: `app.py`**
3. Add your Anthropic API key under the app's **Settings → Secrets**:
   ```
   ANTHROPIC_API_KEY = "sk-ant-your-actual-key-here"
   ```

---

## New in this update: cross-field consistency checks & SGX reference check

**Cross-field consistency checks** (in `logic.py`, used in `step2.py`):

After uploading an identity/registration document for a controller, the
app now compares the extracted fields against the RORC entry:

- Individuals: full name, NRIC/passport number, nationality, date of birth
- Corporates: entity name, UEN/registration number, registered office
  address, legal form

If any field genuinely differs (not just missing/unclear on one side), the
app shows a 🔴 flag, e.g. "ID / passport number on the uploaded document
('S9999999Z') does not match the RORC entry ('S1234567A')". These flags
also appear in the PDF report and affect the overall PASS / PASS WITH GAPS
status.

To see this in the demo: when uploading `04_Tan_Wei_Ming_NRIC.pdf` for Tan
Wei Ming, all fields should match (✅ no conflicts). To see a flag fire,
upload a different person's identity document for the wrong slot — e.g.
upload `08_Raymond_Koh_NRIC.pdf` for Tan Wei Ming's identity verification —
and the NRIC number and name mismatches should be flagged.

**SGX-listed reference check** (`sgx_listed_companies.py`, used in
`step2.py`):

When a user selects the "Public company listed on SGX" or "SGX-listed
corporation (SFA definition)" exemption category — either at the top of an
indirect chain, or for an unexplained ≥25% holder — the app checks the
entity's name against a bundled, offline list of ~466 SGX-listed company
names (derived from a public Wikipedia snapshot, data as of ~2020).

- ✅ Match found → shown as supporting evidence for the exemption claim
- ⚠ No match → the app notes the list is indicative/dated and recommends
  uploading an SGX listing printout or current Bizfile extract regardless

**This list is for demo purposes only** — it is not current or
authoritative. Production use should replace `SGX_LISTED_COMPANIES` with a
live feed (see "Future integrations" below).

---

## Future integrations (not built in this prototype)

- **OpenSanctions / PEP screening** — OpenSanctions offers a usable free
  API tier covering OFAC, UN, EU, UK and other sanctions lists. Could be
  added as a check for each natural person identified, by name. Would
  need: an OpenSanctions API key, a new `external_verification.py` module,
  and careful UI framing since name-matching produces false positives
  requiring human review.

- **MAS Financial Institution Directory** — MAS publishes some open data
  on regulated financial institutions, but it's fragmented across licence
  types. Could support the "Singapore financial institution" exemption
  category similarly to the SGX check, but would need more work to compile
  a usable reference list.

- **Foreign exchange listings** (NYSE, LSE, Bursa Malaysia, etc.) — no
  single source covers these; this remains a "soft stop" requiring legal
  confirmation, as currently implemented.

- **ACRA Bizfile API** — would allow live lookups of UEN, registered
  address, shareholders, etc. instead of relying on user-uploaded Bizfile
  PDFs. Requires registration as an API consumer with ACRA (a commercial
  agreement), not a simple API-key signup — out of scope for a prototype.

- **A live SGX data feed** — SGX appears to have an underlying public JSON
  API (used by some third-party scrapers) but it is undocumented; before
  relying on it in production it should be tested directly with a fallback
  plan if it changes without notice.

---



### Step 1

Upload:
- **RORC** → `01_RORC.pdf`
- **Register of Members** → `02b_Register_of_Members_with_gap.pdf`
  (this variant includes Skyline Ventures Pte Ltd at 28%, which is *not*
  in the RORC — use this to demonstrate the unexplained-holder flow)

Click **Parse documents**, confirm both, then review the three RORC
controllers and their Register of Members matches:

| Controller | Register of Members |
|---|---|
| Tan Wei Ming | 30% |
| Meridian Capital Pte Ltd | 35% |
| John Tan | 7% |

Set the dropdowns:
- **Tan Wei Ming**: mechanism = "Holds more than 25% of shares", **Direct**
- **Meridian Capital Pte Ltd**: mechanism = "Holds more than 25% of
  shares", **Indirect** (triggers chain tracing in Step 2)
- **John Tan**: mechanism = "Holds more than 25% of shares", **Direct**
  (this will trigger the mismatch explanation in Step 2, since Register
  of Members shows only 7%)

You'll also see the warning that **Skyline Ventures Pte Ltd (28%)** is not
in the RORC.

Tick the confirmation checkbox and **Proceed to Step 2**.

### Step 2

**Card 1 — Tan Wei Ming:**
- Annual notice: select document type "Annual Notice (s.386AG)", upload
  `03_Annual_Notice_Tan_Wei_Ming.pdf` → should show "matched_confirmed"
- Identity: select "NRIC", upload `04_Tan_Wei_Ming_NRIC.pdf`
- Mark as resolved

**Card 2 — Meridian Capital Pte Ltd:**
- Annual notice: no notice available for this one — you can skip upload
  and note the "No annual notice provided" flag, or explain in the chain
  section
- Identity: select "ACRA Business Profile / Certificate of Incorporation",
  upload `05_Meridian_Capital_Bizfile.pdf`
- **Trace indirect control**: set chain entities = 1, name "Sarah Lim",
  type "individual" → upload `06_Sarah_Lim_Passport.pdf` (select document
  type "Passport"). The chain should show "Chain terminates at natural
  person: Sarah Lim"
- Mark as resolved

**Card 3 — John Tan:**
- Annual notice: select "Annual Notice (s.386AG)", upload
  `03b_Annual_Notice_John_Tan_no_reply.pdf` → should show
  "matched_no_reply"
- Identity: select "NRIC", upload `07_John_Tan_NRIC.pdf`
- **Register of Members mismatch**: explain, e.g. "Remaining 8% interest
  held via joint voting arrangement with Tan Wei Ming — to be
  documented." Optionally upload a supporting document.
- Mark as resolved

**Card 4 — Skyline Ventures Pte Ltd (28%, not in RORC):**
- Select **"Yes"** — Skyline is a nominee shareholder
- Upload `09_Skyline_Nominee_Document.pdf` (document type: "Nominee
  agreement / correspondence") → should extract nominator = "Raymond Koh"
- Clarifying question: select **"Yes — Raymond Koh is the beneficial
  owner"**
- Identity verification for Raymond Koh: select "NRIC", upload
  `08_Raymond_Koh_NRIC.pdf`
- Note the prompt that an annual notice should be sent to Raymond Koh
  going forward
- Mark as resolved

**Proceed to Step 3.**

### Step 3

Review the summary — all four items should show "Resolved". Generate and
download the PDF report.

---

## Notes / simplifications in this prototype

- All document uploads accept PDF, JPG, and PNG. Extracted fields are
  shown as **editable text inputs** so users can correct OCR mistakes,
  especially for photographed identity documents.
- The chain-trace step lets the user manually enter the chain (name,
  type, exemption category) rather than the AI inferring it automatically.
- "Resolved" status is a manual checkbox per card.
- The annual notice is required per-controller in the UI sense (the app
  will show a 🔴 "No annual notice provided" flag if skipped), but the
  user can still proceed without uploading one — the gap is surfaced in
  the report rather than hard-blocking, consistent with the idea that the
  *absence* of the notice is itself the finding the report should
  highlight.
