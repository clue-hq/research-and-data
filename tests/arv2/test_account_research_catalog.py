"""The arv2-account catalog: five files, sha-pinned; the manual covers every refusal code."""

import datetime
import hashlib
import json
import re

from clue_api.arv2.account_research_catalog import (
    ARV2_ACCOUNT_PROFILE_REF,
    AccountContext,
    arv2_account_catalog_root,
    arv2_account_profile_sha256,
    build_system_prompt,
    load_account_resources,
)
from clue_api.arv2.account_research_refusals import REFUSAL_CODES, refusal_json

FILES = ("profile.md", "prompt.md", "dossier.md", "audit.md", "manual.md")


def test_five_files_exist_and_the_profile_sha_is_the_file_digest() -> None:
    root = arv2_account_catalog_root()
    for name in FILES:
        assert (root / name).is_file(), name
    assert (
        arv2_account_profile_sha256()
        == hashlib.sha256((root / "profile.md").read_bytes()).hexdigest()
    )
    assert ARV2_ACCOUNT_PROFILE_REF == "agent-profile:arv2-account:v1"


def test_bundle_carries_one_prompt_and_three_skills_with_matching_digests() -> None:
    bundle = load_account_resources()
    assert bundle.prompt.ref == "agent-prompt:arv2-account:v1"
    assert [s.ref for s in bundle.skills] == [
        "agent-skill:arv2-account-dossier:v1",
        "agent-skill:arv2-account-audit:v1",
        "agent-skill:arv2-account-manual:v1",
    ]
    for resource in (bundle.profile, bundle.prompt, *bundle.skills):
        assert resource.sha256 == hashlib.sha256(resource.body.encode()).hexdigest()
    assert len(bundle.manifest_sha256()) == 64


def test_manual_names_every_refusal_code_the_driver_can_emit() -> None:
    manual = (arv2_account_catalog_root() / "manual.md").read_text(encoding="utf-8")
    named = set(re.findall(r"`([a-z_]+(?::<[a-z_]+>)?)`", manual))
    missing = {code for code in REFUSAL_CODES if code not in named}
    assert not missing, f"manual.md lacks a row for: {sorted(missing)}"


def test_refusal_envelope_is_recoverable_json_with_the_manual_reaction() -> None:
    body = json.loads(refusal_json("board_not_found", "no ATS link on /careers"))
    assert body["error"] == "governed_research_rejection"
    assert body["code"] == "board_not_found" and body["recoverable"] is True
    assert "careers page" in body["reaction"]


def test_system_prompt_stacks_profile_prompt_skills_and_the_context_block() -> None:
    bundle = load_account_resources()
    context = AccountContext(
        account_name="Probook",
        account_domain="probook.ai",
        account_id="00000000-0000-0000-0000-000000000001",
        workspace_id="ws",
        today=datetime.date(2026, 9, 8),
        icp_markdown="# ICP\nhard_gates: []",
        persona_markdown="personas: []",
        catalog_menu="- account.named_customers",
        already_established="- HQ: New York",
        directive_text="",
        effort="full",
        committee_cap=5,
        stop_policy={
            "max_model_rounds": 100,
            "max_tool_calls_per_round": 50,
            "max_runtime_s": 1800,
        },
    )
    prompt = build_system_prompt(bundle, context)
    for marker in (
        '<profile ref="agent-profile:arv2-account:v1"',
        bundle.prompt.body[:40],
        '<skill ref="agent-skill:arv2-account-dossier:v1"',
        "<account_research_context>",
        "probook.ai",
        "# ICP",
        "- account.named_customers",
        "2026-09-08",
    ):
        assert marker in prompt
