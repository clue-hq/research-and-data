"""The arv2-account catalog: five files, sha-pinned; the manual covers every refusal code."""

import datetime
import hashlib
import json
import re
from typing import Any

from clue_api.arv2.account_research_catalog import (
    ARV2_ACCOUNT_PROFILE_REF,
    AccountContext,
    arv2_account_catalog_root,
    arv2_account_profile_sha256,
    build_system_prompt,
    load_account_resources,
)
from clue_api.arv2.account_research_refusals import REACTIONS, REFUSAL_CODES, refusal_json

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


def test_the_launch_pin_and_the_bundle_agree_on_the_profile_digest(tmp_path: Any) -> None:
    """One digest computation, so the launch pin can never differ from the digest the driver checks.

    The two were computed independently — the pin over the file's raw bytes, the bundle over the
    decoded text — so a profile written with CRLF line endings pinned one digest at launch and
    failed the driver's comparison against the other, refusing every job of that run.
    """
    root = tmp_path / "v1"
    root.mkdir()
    for name in FILES:
        (root / name).write_bytes(b"# " + name.encode() + b"\r\nline two\r\n")

    assert arv2_account_profile_sha256(root) == load_account_resources(root).profile.sha256


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


def test_every_reaction_is_the_manual_row_word_for_word() -> None:
    """The guard ``account_research_refusals``'s docstring already claims exists.

    ``refusal_json`` embeds ``reaction`` in the envelope the model reads *in the same turn*, so a
    reaction that has drifted from the manual is a more proximate instruction than the manual
    itself. The R2 follow-ups slice rewrote the ``feed_not_found`` row and left the table behind;
    the old test only checked that each code was *named* somewhere in the file.
    """
    manual = (arv2_account_catalog_root() / "manual.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*`([a-z_]+)`\s*\|(?:[^|]*)\|([^|]*)\|\s*$", manual, re.MULTILINE)
    covered = {code for code, _ in rows} & set(REFUSAL_CODES)
    assert covered == set(REFUSAL_CODES), (
        f"manual.md has no reaction row for: {sorted(set(REFUSAL_CODES) - covered)}"
    )
    drifted = {
        code: (REACTIONS[code], reaction.strip())
        for code, reaction in rows
        if code in REACTIONS and REACTIONS[code] != reaction.strip()
    }
    assert not drifted, f"REACTIONS and manual.md disagree: {drifted}"


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
        icp_gate_keys=("series-a-saas", "us-hq"),
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
        # The gates the finalization's verdicts are keyed to: the model is told the keys rather
        # than left to invent labels the tool would then refuse.
        '"icp_gate_keys": ["series-a-saas", "us-hq"]',
        "exactly one verdict per key in `icp_gate_keys`",
    ):
        assert marker in prompt
