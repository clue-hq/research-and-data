"""Preserve the compiler's actionable diagnostics at the agent tool boundary."""

import pytest
from lumen_agent.tools.substrate import diagnostics_from


@pytest.mark.parametrize("target_kind", ["node", "page", "slot"])
@pytest.mark.parametrize("wrapped", [False, True], ids=["flat", "dsl_wrapper"])
def test_diagnostic_details_survive_tool_normalization(target_kind, wrapped):
    diagnostic = {
        "severity": "error",
        "code": "LUMD0800",
        "message": "parent node chip does not exist",
        "hint": "Create the parent before moving its child.",
        "subject": {"kind": target_kind, "id": "chip"},
    }
    span = {"line": 3, "column": 1, "length": 19}
    raw = {"diagnostic": diagnostic, "span": span} if wrapped else {**diagnostic, "span": span}

    [summary] = diagnostics_from([raw])

    assert summary.severity.value == "error"
    assert summary.code == diagnostic["code"]
    assert summary.message == diagnostic["message"]
    assert summary.suggested_repair == diagnostic["hint"]
    assert (summary.line, summary.column) == (3, 1)
    assert getattr(summary, f"target_{target_kind}_id") == "chip"


def test_malformed_diagnostic_wrapper_keeps_flat_fallback():
    [summary] = diagnostics_from(
        [{"diagnostic": "invalid", "severity": "warning", "message": "Still actionable"}]
    )

    assert summary.severity.value == "warning"
    assert summary.message == "Still actionable"
