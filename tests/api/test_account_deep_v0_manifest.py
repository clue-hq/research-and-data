"""The M8B V0 acceptance matrix is complete and points to executable tests."""

from __future__ import annotations

import ast
import json
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_MANIFEST = _REPO / "tests/fixtures/account_deep/v0_fault_matrix.json"
_REQUIRED_CASES = {
    "eligibility_sealed_batch",
    "eligibility_pass_a",
    "eligibility_must_haves",
    "eligibility_human_tier",
    "eligibility_committee_plan",
    "eligibility_governance",
    "eligibility_fresh_snapshot",
    "launch_duplicate_concurrent",
    "crash_before_dispatch",
    "crash_after_dispatch",
    "crash_after_response_before_snapshot",
    "crash_after_snapshot_before_materialization",
    "crash_after_claim_before_fold",
    "people_pending_running_succeeded_repeated_poll",
    "people_failed",
    "exa_missing_grounding",
    "exa_additive_drift",
    "exa_timeout",
    "exa_4xx",
    "exa_429",
    "exa_5xx",
    "exa_spend_unknown",
    "sumble_charged_schema_drift",
    "snapshot_stale_fresh",
    "source_contradiction_merge_preservation",
    "account_identity_drift",
    "same_name_contact_collision",
    "budget_rejection",
    "jurisdiction_rejection",
    "use_class_rejection",
    "dsar_enumerate_tombstone_replay",
    "fresh_process_replay_and_inspection",
}


def test_v0_fault_matrix_is_complete_and_every_entry_is_executable() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert payload["spec"] == "M8B Slice V0"
    assert payload["provider_mode"] == "recorded-fixtures-only"
    cases = payload["cases"]
    case_ids = [case["id"] for case in cases]
    assert len(case_ids) == len(set(case_ids))
    assert set(case_ids) == _REQUIRED_CASES

    parsed_files: dict[Path, set[str]] = {}
    for case in cases:
        relative_path, function_name = case["nodeid"].split("::", maxsplit=1)
        test_path = _REPO / relative_path
        assert test_path.is_file(), case
        if test_path not in parsed_files:
            module = ast.parse(test_path.read_text(encoding="utf-8"), filename=str(test_path))
            parsed_files[test_path] = {
                node.name
                for node in module.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
        assert function_name in parsed_files[test_path], case
