"""
extraction.py
=============

Everything related to talking to the Anthropic API to extract structured
data from uploaded documents.

Contains:
  - get_client(): builds the Anthropic client from Streamlit secrets
  - DOCUMENT_TYPE_OPTIONS: the dropdown list of document types a user can
    select when uploading a supporting document
  - Extraction prompts, one per document type:
      RORC_PROMPT, ROM_PROMPT, ANNUAL_NOTICE_PROMPT, NRIC_PROMPT,
      PASSPORT_PROMPT, CORPORATE_PROFILE_PROMPT, NOMINEE_DOC_PROMPT,
      TRUST_DEED_PROMPT, OTHER_DOC_PROMPT
  - extract_document(client, prompt, file_bytes, filename): sends a file
    (PDF, JPG, or PNG) to Claude with the given prompt and returns the
    parsed JSON response. Automatically routes to the correct API content
    block type ("document" for PDF, "image" for JPG/PNG) based on the
    file extension.

Design notes:
  - All prompts are written to tolerate unclear/illegible source documents
    (e.g. photographed NRICs) - fields that cannot be read should come
    back as null/"unclear" rather than being guessed.
  - The calling UI code is responsible for showing extracted fields as
    EDITABLE inputs so the user can correct anything misread.
"""

import streamlit as st
import anthropic
import json
import base64
import os


MODEL = "claude-sonnet-4-6"


def get_client():
    api_key = st.secrets.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY"))
    if not api_key:
        st.error("No Anthropic API key found. Add ANTHROPIC_API_KEY to your Streamlit secrets.")
        st.stop()
    return anthropic.Anthropic(api_key=api_key)


# =============================================================================
# DOCUMENT TYPE OPTIONS (for supporting document uploads in Step 2)
# =============================================================================
DOCUMENT_TYPE_OPTIONS = [
    "NRIC",
    "Passport",
    "ACRA Business Profile / Certificate of Incorporation",
    "Annual Notice (s.386AG)",
    "Nominee agreement / correspondence",
    "Trust deed",
    "Other",
]


# =============================================================================
# PRIMARY EXTRACTION PROMPTS (Step 1)
# =============================================================================
RORC_PROMPT = """You are reading a company's Register of Registrable Controllers (RORC),
maintained under Part 11A of the Singapore Companies Act 1967. ACRA requires
the RORC to contain specific fields depending on whether the controller is
an individual, a corporate entity, or (where no controller can be identified)
a director with executive control / CEO recorded as a fallback.

Extract every entry. For EACH entry, determine its category
("individual", "corporate", or "fallback_director") and extract the
following fields (use null for any field not present in the document):

For "individual" or "fallback_director":
- full_name
- aliases
- residential_address
- email
- contact_number
- nationality
- id_number (NRIC or passport number)
- date_of_birth
- date_became_controller
- date_ceased (null if still a controller)

For "corporate":
- name
- uen (Unique Entity Number, if any)
- registered_office_address
- email
- contact_number
- legal_form
- jurisdiction_and_statute (jurisdiction where formed/incorporated and under which law)
- corporate_registrar_name (if applicable)
- identification_or_registration_number (on the corporate registrar, if applicable)
- date_became_controller
- date_ceased (null if still a controller)

Also extract, if stated in the document:
- nature_of_control (free text as written in the RORC, if any)
- percentage (number, if stated)
- confirmed (true/false - whether particulars were confirmed by the controller; default true if not mentioned)

Respond ONLY with valid JSON, no other text:
{
  "document_type": "RORC",
  "company_name": "...",
  "entries": [
    {
      "category": "individual" | "corporate" | "fallback_director",
      "full_name": "...", "aliases": "...", "residential_address": "...",
      "email": "...", "contact_number": "...", "nationality": "...",
      "id_number": "...", "date_of_birth": "...",
      "name": "...", "uen": "...", "registered_office_address": "...",
      "legal_form": "...", "jurisdiction_and_statute": "...",
      "corporate_registrar_name": "...", "identification_or_registration_number": "...",
      "date_became_controller": "...", "date_ceased": null,
      "nature_of_control": "...", "percentage": ..., "confirmed": true
    }
  ]
}
Only include the fields relevant to the entry's category; set irrelevant fields to null."""


ROM_PROMPT = """You are reading a company's Register of Members (shareholder
register), maintained under the Singapore Companies Act 1967.

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
}"""


# =============================================================================
# SUPPORTING DOCUMENT PROMPTS (Step 2) - one per document type
# =============================================================================
ANNUAL_NOTICE_PROMPT = """You are reading a notice issued under section 386AG(2) of the
Singapore Companies Act 1967 (the annual notice sent by a company to a person
it believes is a registrable controller, requiring them to confirm their
particulars). The document may be a clean PDF or a scanned/photographed copy
- if any field is unclear or illegible, use "unclear" rather than guessing.

Extract:
- company_name: the company that sent the notice
- addressee_name: the name of the person/entity the notice is addressed to (if stated)
- date_of_notice
- reply_given: true/false - whether the form appears to have been filled in and signed/dated by the addressee
- reply_confirms_controller: true/false/null - based on Question 1 ("Are you a registrable controller?"), did the addressee answer Yes? null if not answered or unclear.
- particulars_provided: a short list of strings summarising what particulars (if any) the addressee provided in their reply
- another_controller_identified: true/false/null - based on Question 2, did the addressee indicate they know of another possible controller?
- another_controller_details: a short list of strings with any details given about the other possible controller (empty list if none)

Respond ONLY with valid JSON, no other text:
{
  "document_type": "Annual Notice",
  "company_name": "...",
  "addressee_name": "...",
  "date_of_notice": "...",
  "reply_given": true,
  "reply_confirms_controller": true,
  "particulars_provided": ["..."],
  "another_controller_identified": false,
  "another_controller_details": []
}"""


NRIC_PROMPT = """You are reading a Singapore NRIC (National Registration Identity Card).
This may be a clean scan or a photograph (possibly at an angle, with glare,
or partially cropped). Extract what you can read. If a field is illegible or
not visible, return "unclear" for that field rather than guessing.

Extract:
- full_name
- nric_number
- nationality (usually "Singapore Citizen" or "Singapore Permanent Resident")
- date_of_birth
- address (if visible on the card)

Respond ONLY with valid JSON, no other text:
{
  "doc_category": "identity_individual",
  "document_subtype": "NRIC",
  "full_name": "...",
  "nric_number": "...",
  "nationality": "...",
  "date_of_birth": "...",
  "address": "..."
}"""


PASSPORT_PROMPT = """You are reading a passport (the photo/data page). This may be a
clean scan or a photograph (possibly at an angle, with glare, or partially
cropped). Extract what you can read. If a field is illegible or not visible,
return "unclear" for that field rather than guessing.

Extract:
- full_name
- passport_number
- nationality
- date_of_birth
- date_of_expiry (if visible)

Respond ONLY with valid JSON, no other text:
{
  "doc_category": "identity_individual",
  "document_subtype": "Passport",
  "full_name": "...",
  "passport_number": "...",
  "nationality": "...",
  "date_of_birth": "...",
  "date_of_expiry": "..."
}"""


CORPORATE_PROFILE_PROMPT = """You are reading an ACRA Business Profile extract (Bizfile) or
a Certificate of Incorporation (Singapore or foreign jurisdiction). Extract
what you can read. If a field is not present or illegible, return "unclear"
or null as appropriate.

Extract:
- entity_name
- registration_number (UEN for Singapore entities, or equivalent for foreign entities)
- entity_type / legal_form
- incorporation_date
- jurisdiction
- registered_address
- status (e.g. "Live", "Struck off", etc, if shown)
- shareholders: a short list of strings describing shareholders and their percentages, if shown (e.g. "Sarah Lim - 100%")
- directors: a short list of strings with director names, if shown

Respond ONLY with valid JSON, no other text:
{
  "doc_category": "corporate_profile",
  "document_subtype": "ACRA Business Profile / Certificate of Incorporation",
  "entity_name": "...",
  "registration_number": "...",
  "entity_type": "...",
  "incorporation_date": "...",
  "jurisdiction": "...",
  "registered_address": "...",
  "status": "...",
  "shareholders": ["..."],
  "directors": ["..."]
}"""


NOMINEE_DOC_PROMPT = """You are reading a document evidencing a nominee shareholder
arrangement - this could be a Register of Nominee Shareholders (RONS) entry,
a nominee agreement, or correspondence describing the arrangement. Extract
what you can read. If a field is not present or illegible, return "unclear"
or null as appropriate.

Extract:
- nominee_name: the person/entity holding shares as nominee
- nominator_name: the person/entity on whose behalf the shares are held (the nominator)
- nominator_type: "individual" or "corporate"
- shares_or_percentage: description of the shareholding involved (e.g. "250,000 shares (25%)")
- date_of_arrangement (if stated)
- other_details: a short list of strings with any other relevant details

Respond ONLY with valid JSON, no other text:
{
  "doc_category": "nominee_arrangement",
  "document_subtype": "Nominee agreement / correspondence",
  "nominee_name": "...",
  "nominator_name": "...",
  "nominator_type": "...",
  "shares_or_percentage": "...",
  "date_of_arrangement": "...",
  "other_details": ["..."]
}"""


TRUST_DEED_PROMPT = """You are reading a trust deed or extract relating to an express
trust under Part 7 of the Trustees Act 1967, provided as evidence that a
shareholder is acting as trustee (relevant to the RORC exemption for
trustees of express trusts). Extract what you can read. If a field is not
present or illegible, return "unclear" or null as appropriate.

Extract:
- trustee_name: the name of the trustee
- trust_name: the name of the trust (if stated)
- settlor_name (if stated)
- beneficiaries: a short list of strings naming beneficiaries (if stated)
- date_of_trust_deed (if stated)
- other_details: a short list of strings with any other relevant details

Respond ONLY with valid JSON, no other text:
{
  "doc_category": "trust_deed",
  "document_subtype": "Trust deed",
  "trustee_name": "...",
  "trust_name": "...",
  "settlor_name": "...",
  "beneficiaries": ["..."],
  "date_of_trust_deed": "...",
  "other_details": ["..."]
}"""


OTHER_DOC_PROMPT = """You are reading a supporting document submitted as evidence in a
Singapore beneficial ownership (RORC) validation. The document type was not
specified by the user. Read the document and summarise what it appears to
show. If a field is not present or illegible, return "unclear" or null as
appropriate.

Extract:
- apparent_subject: the name of the individual/entity this document appears to be about (if identifiable)
- apparent_purpose: a short description of what this document appears to be (e.g. "utility bill for address verification", "board resolution")
- key_facts: a short list of strings describing relevant facts found in the document

Respond ONLY with valid JSON, no other text:
{
  "doc_category": "other",
  "document_subtype": "Other",
  "apparent_subject": "...",
  "apparent_purpose": "...",
  "key_facts": ["..."]
}"""


SUPPORTING_PROMPTS_BY_TYPE = {
    "NRIC": NRIC_PROMPT,
    "Passport": PASSPORT_PROMPT,
    "ACRA Business Profile / Certificate of Incorporation": CORPORATE_PROFILE_PROMPT,
    "Annual Notice (s.386AG)": ANNUAL_NOTICE_PROMPT,
    "Nominee agreement / correspondence": NOMINEE_DOC_PROMPT,
    "Trust deed": TRUST_DEED_PROMPT,
    "Other": OTHER_DOC_PROMPT,
}


# =============================================================================
# DOCUMENT EXTRACTION
# =============================================================================
IMAGE_EXTENSIONS = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}


def extract_document(client, prompt, file_bytes, filename="document.pdf"):
    """
    Send a file (PDF, JPG, or PNG) to Claude for structured extraction using
    the given prompt. Routes to the correct API content block type based on
    the file extension. Returns the parsed JSON response as a dict.
    """
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else "pdf"
    b64 = base64.standard_b64encode(file_bytes).decode("utf-8")

    if ext in IMAGE_EXTENSIONS:
        content_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": IMAGE_EXTENSIONS[ext], "data": b64},
        }
    else:
        content_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
        }

    message = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": [content_block, {"type": "text", "text": prompt}],
        }],
    )
    text = "".join(b.text for b in message.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)
