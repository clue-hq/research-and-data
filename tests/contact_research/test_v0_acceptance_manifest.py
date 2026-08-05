"""M8C V0 exit-gate coverage is complete and points to executable evidence."""

from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_MANIFEST = _REPO / "tests/fixtures/contact_research/v0_acceptance_matrix.json"
_ROADMAP = _REPO / "docs/specs/M8C-contact-deep-research-and-selected-contact-enrichment-roadmap.md"
_C0_ACCEPTANCE = _REPO / "docs/specs/M8C-C0-contact-research-contract-acceptance.md"
_EXPECTED_GATES = {
    *(f"C0.{index}" for index in range(1, 9)),
    *(f"C1.{index}" for index in range(1, 8)),
    *(f"C2.{index}" for index in range(1, 9)),
    *(f"C3.{index}" for index in range(1, 6)),
    *(f"C4.{index}" for index in range(1, 8)),
    *(f"C5.{index}" for index in range(1, 9)),
    *(f"C6.{index}" for index in range(1, 7)),
    *(f"C7.{index}" for index in range(1, 7)),
}
_EXPECTED_COMMAND_GATES = {
    "single_alembic_head",
    "migration_reversibility",
    "mypy",
    "ruff_format",
    "ruff_lint",
    "import_linter",
    "full_repository_regression",
}


def _assert_nodeids_exist(nodeids: set[str]) -> None:
    parsed_files: dict[Path, set[str]] = {}
    for nodeid in nodeids:
        relative_path, function_name = nodeid.split("::", maxsplit=1)
        test_path = _REPO / relative_path
        assert test_path.is_file(), nodeid
        if test_path not in parsed_files:
            module = ast.parse(test_path.read_text(encoding="utf-8"), filename=str(test_path))
            parsed_files[test_path] = {
                node.name
                for node in module.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
        assert function_name in parsed_files[test_path], nodeid


def test_v0_matrix_covers_every_slice_gate_and_required_category() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert payload["spec"] == "M8C Slice V0"
    assert payload["provider_mode"] == "fake-transports-only"
    assert payload["database_mode"] == "fresh-isolated-postgres-with-synthetic-prerequisites"

    cases = payload["cases"]
    gates = [case["gate"] for case in cases]
    assert len(gates) == len(set(gates))
    assert set(gates) == _EXPECTED_GATES
    assert Counter(gate.split(".", maxsplit=1)[0] for gate in gates) == payload["slice_gate_counts"]

    support_cases = payload["support_cases"]
    command_gates = payload["command_gates"]
    assert {gate["id"] for gate in command_gates} == _EXPECTED_COMMAND_GATES
    observed_categories = {
        *(case["category"] for case in cases),
        *(case["category"] for case in support_cases),
        *(gate["category"] for gate in command_gates),
    }
    assert observed_categories == set(payload["required_categories"])

    nodeids = {
        payload["prerequisite_fixture"]["nodeid"],
        *(case["nodeid"] for case in cases),
        *(case["nodeid"] for case in support_cases),
    }
    _assert_nodeids_exist(nodeids)


def test_c0_acceptance_record_is_frozen_before_later_slice_execution() -> None:
    acceptance = _C0_ACCEPTANCE.read_text(encoding="utf-8")
    roadmap = _ROADMAP.read_text(encoding="utf-8")
    assert "**Frozen:** 2026-08-05" in acceptance
    assert "mechanically accepted after adversarial authority/contract remediation" in acceptance
    assert "no migration,\n  live provider request, reveal, or identity mutation" in acceptance
    assert "### C0 — Contract, field, and policy freeze" in roadmap
    assert "### C1 — Sumble snapshot-backed professional fact materialization" in roadmap
