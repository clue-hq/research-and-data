"""Answer-key mapping rules (plan decisions 4-8, 10)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from clue_api.arv2.answer_key import (
    PERSONA_MAP,
    WORK_EMAIL_KEY,
    ZAFRAN_MANIFEST,
    map_people_rows,
    map_zafran_rows,
    priority_for,
    resolve_source_url,
    work_email_value,
)
from clue_core import EntityType, ExtractionMethod, IdentityBinding, Persona, UseClass

REPO = Path(__file__).resolve().parents[2]
ZAFRAN = json.loads((REPO / ".context/arv2-one-account-aiark/claims_zafran.json").read_text())
PEOPLE = json.loads((REPO / ".context/arv2-person-depth/claims_people.json").read_text())
ROSTER = json.loads((REPO / ".context/arv2-person-depth/roster.json").read_text())


def test_resolve_source_url() -> None:
    assert resolve_source_url("https://www.zafran.io/about") == "https://www.zafran.io/about"
    assert resolve_source_url("BUNDLE: SOURCE A") is None
    assert resolve_source_url("BUNDLE: SOURCE A / SOURCE B") == "https://www.zafran.io/"
    assert resolve_source_url("BUNDLE: SOURCE B / SOURCE C") == "https://www.zafran.io/"
    assert (
        resolve_source_url("https://www.zafran.io/x / BUNDLE: SOURCE A")
        == "https://www.zafran.io/x"
    )
    assert resolve_source_url(None) is None


def test_priority_table() -> None:
    assert priority_for("account.open_requisitions", EntityType.ACCOUNT) == 1
    assert priority_for("account.recent_funding", EntityType.ACCOUNT) == 2
    assert priority_for("core.account_name", EntityType.ACCOUNT) == 3
    assert priority_for("contact.facet.hobby", EntityType.CONTACT) == 2
    assert priority_for("contact.current_title", EntityType.CONTACT) == 3


def test_zafran_rows_map_completely() -> None:
    mapped = map_zafran_rows(ZAFRAN)
    reasons = Counter(skip.reason for skip in mapped.skips)
    assert reasons == {"not_found": 4, "duplicate_persona": 1}
    assert {s.source_row_id for s in mapped.skips if s.reason == "not_found"} == {
        "zaf-130",
        "zaf-131",
        "zaf-132",
        "zaf-133",
    }
    assert len(mapped.drafts) == 174 - 5
    subjects = {d.subject for d in mapped.drafts}
    assert "account:zafran.io" in subjects
    assert {s for s in subjects if s.startswith("contact:")} == {
        "contact:https://www.linkedin.com/in/nicholastfisher",
        "contact:https://www.linkedin.com/in/sanaz-yashar",
        "contact:https://www.linkedin.com/in/varinderkaur",
        "contact:https://www.linkedin.com/in/tomanthonyjr",
        "contact:https://www.linkedin.com/in/ben-seri",
    }
    personas = {d.subject: d.value_json for d in mapped.drafts if d.field_key == "contact.persona"}
    assert personas["contact:https://www.linkedin.com/in/sanaz-yashar"] == "economic_buyer"
    assert personas["contact:https://www.linkedin.com/in/tomanthonyjr"] == "user"
    assert all(Persona(v) for v in personas.values())
    roles = [d for d in mapped.drafts if d.field_key == "contact.role_on_committee"]
    assert all(
        isinstance(d.value_json, dict) and d.value_json["role"] == personas[d.subject]
        for d in roles
    )
    by_id = {d.source_row_id: d for d in mapped.drafts}
    assert by_id["zaf-001"].extraction_method is ExtractionMethod.API
    assert by_id["zaf-001"].source_url is None
    assert by_id["zaf-119"].extraction_method is ExtractionMethod.LLM_SYNTHESIS
    assert by_id["zaf-119"].source_url == "https://www.zafran.io/"
    assert by_id["zaf-172"].field_key == "account.claimed_customer_logos"
    media = [d for d in mapped.drafts if d.media_url]
    assert media and all(
        isinstance(d.value_json, dict)
        and "text" in d.value_json
        and "media_timestamp" in d.value_json
        for d in media
    )
    contact_rows = [d for d in mapped.drafts if d.entity_type is EntityType.CONTACT]
    assert all(
        d.identity_binding in (IdentityBinding.STRONG, IdentityBinding.WEAK) for d in contact_rows
    )
    assert all(d.use_class is not None for d in contact_rows)
    assert all(d.use_class is None for d in mapped.drafts if d.entity_type is EntityType.ACCOUNT)
    assert sum(1 for d in mapped.drafts if not d.outreach_safe) == 11  # 12 unsafe minus zaf-132


def test_people_rows_map_completely() -> None:
    mapped = map_people_rows(PEOPLE, ROSTER)
    assert not mapped.skips
    assert len(mapped.drafts) == 119 + 3  # three pipe-joined rows each become two drafts
    assert {d.subject for d in mapped.drafts} == {
        f"contact:{p['linkedin'].lower().rstrip('/')}" for p in ROSTER
    }
    assert all(
        d.extraction_method is ExtractionMethod.LLM_SYNTHESIS and d.source_url and d.evidence_span
        for d in mapped.drafts
    )
    assert all(d.identity_binding is IdentityBinding.STRONG for d in mapped.drafts)
    assert {d.use_class for d in mapped.drafts} == {
        UseClass.PROFESSIONAL_PUBLIC,
        UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
    }
    assert Counter(d.signal_priority for d in mapped.drafts)[1] >= 83
    joined = [d for d in mapped.drafts if "pipe_joined_key" in d.markers]
    assert len(joined) == 6 and all("|" not in d.field_key for d in joined)


def test_manifest_names_the_five_accounts_twelve_people_and_two_documents() -> None:
    assert {a.domain for a in ZAFRAN_MANIFEST.accounts} == {
        "zafran.io",
        "cogent.com",
        "harmonic.security",
        "uptiq.ai",
        "probook.ai",  # the second fixed answer key — entity only; R2 researches it live
    }
    assert {d.kind for d in ZAFRAN_MANIFEST.documents} == {"icp-definition", "audience-persona"}
    assert all(d.path.startswith("audience/") for d in ZAFRAN_MANIFEST.documents)
    assert ZAFRAN_MANIFEST.icp_key == "clue-abm-buyers"
    # Ten from the person-depth roster plus Tom Anthony and Ben Seri, who appear only in the
    # Zafran committee rows: the loader has to create an entity for every subject either file names.
    assert len(ZAFRAN_MANIFEST.people) == 12 and len(ZAFRAN_MANIFEST.media) == 3
    assert PERSONA_MAP == {"executive_sponsor": "economic_buyer", "adjacent_buyer": "user"}


def test_work_email_carries_the_providers_verdict() -> None:
    """D4-b decision 6: the address and the grading that makes it usable travel together."""
    mapped = map_zafran_rows(ZAFRAN)
    emails = {d.source_row_id: d.value_json for d in mapped.drafts if d.field_key == WORK_EMAIL_KEY}
    assert set(emails) == {"zaf-083", "zaf-084", "zaf-085", "zaf-086"}
    assert emails["zaf-084"] == {
        "address": "nick@zafran.io",
        "status": "verified_smtp",
        "checked_at": "2026-08-31T07:52:05.000725",
    }
    assert all(
        isinstance(value, dict) and value["status"] == "verified_smtp" for value in emails.values()
    )


def test_work_email_value_grades_what_the_provider_said_and_nothing_more() -> None:
    # A verification block the run recorded: verdict and check time, kept verbatim.
    assert work_email_value(
        "nick@zafran.io", {"verdict": "catch_all_valid", "checked_at": "2026-08-31T07:52:05"}
    ) == {
        "address": "nick@zafran.io",
        "status": "catch_all_valid",
        "checked_at": "2026-08-31T07:52:05",
    }
    # No block at all: nobody probed the mailbox — which is not the same as a failed probe.
    assert work_email_value("nick@zafran.io", None) == {
        "address": "nick@zafran.io",
        "status": "unverified",
    }
    # A verdict outside the registered vocabulary (AI Ark's ``not_found``, a future label) is
    # graded ``unknown`` rather than stored as-is, and a block with no check time carries none.
    assert work_email_value("nick@zafran.io", {"verdict": "not_found"}) == {
        "address": "nick@zafran.io",
        "status": "unknown",
    }
    assert work_email_value("nick@zafran.io", {}) == {
        "address": "nick@zafran.io",
        "status": "unknown",
    }
    # A value that is not an address is left exactly as the run recorded it.
    assert work_email_value(None, {"verdict": "verified_smtp"}) is None
