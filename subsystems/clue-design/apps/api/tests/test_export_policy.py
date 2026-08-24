"""Unit tests for the export BLOCKING/ADVISORY diagnostic classification.

The behavior these pin down is a safety property: the classification is
fail-closed, so a code nobody has classified refuses the export rather than
silently shipping. Widening the advisory set must always be deliberate.
"""

from __future__ import annotations

from lumen_api.export_policy import (
    ADVISORY_EXPORT_DIAGNOSTIC_CODES,
    export_warning_views,
    has_blocking_export_diagnostics,
    is_advisory_export_diagnostic,
    is_blocking_export_diagnostic,
    partition_export_diagnostics,
)


def diagnostic(code: str, severity: str = "error", **extra: object) -> dict:
    return {
        "code": code,
        "severity": severity,
        "message": f"{code} happened",
        "phase": "layout",
        "subject": None,
        "hint": None,
        **extra,
    }


def test_unknown_error_codes_block_by_default() -> None:
    """The fail-closed core. A code from a future engine version, or one nobody
    has classified yet, must refuse the export."""
    assert is_blocking_export_diagnostic(diagnostic("LUMV9999")) is True
    assert has_blocking_export_diagnostics([diagnostic("LUMV9999")]) is True


def test_classified_policy_lint_is_advisory() -> None:
    lint = diagnostic("LUMV0820")
    assert is_blocking_export_diagnostic(lint) is False
    assert is_advisory_export_diagnostic(lint) is True
    assert has_blocking_export_diagnostics([lint]) is False


def test_non_error_severities_are_neither_blocking_nor_advisory() -> None:
    """Warnings and advice were never export-relevant; the split must not
    promote them into the new warnings channel."""
    for severity in ("warning", "advice", "info"):
        item = diagnostic("LUMV0814", severity=severity)
        assert is_blocking_export_diagnostic(item) is False
        assert is_advisory_export_diagnostic(item) is False
    assert export_warning_views(
        [diagnostic("LUMV0814", severity="warning")]
    ) == []


def test_malformed_diagnostic_without_a_code_blocks() -> None:
    """We cannot classify what we cannot identify, so we refuse."""
    assert is_blocking_export_diagnostic({"severity": "error"}) is True
    assert is_blocking_export_diagnostic({"severity": "error", "code": None}) is True


def test_partition_separates_blocking_from_advisory() -> None:
    blocking, advisory = partition_export_diagnostics(
        [
            diagnostic("LUMV0820"),
            diagnostic("LUMV0821"),
            diagnostic("LUMV0814", severity="warning"),
            diagnostic("LUMV0805", severity="advice"),
        ]
    )
    assert [item["code"] for item in blocking] == ["LUMV0821"]
    assert [item["code"] for item in advisory] == ["LUMV0820"]


def test_one_blocking_diagnostic_refuses_even_among_advisories() -> None:
    assert (
        has_blocking_export_diagnostics(
            [diagnostic("LUMV0820"), diagnostic("LUMV0821")]
        )
        is True
    )


def test_warning_views_carry_what_the_editor_needs() -> None:
    views = export_warning_views(
        [
            diagnostic(
                "LUMV0820",
                subject={"kind": "slot", "id": "slot_account_logo"},
                hint="Set one with #slot:key image_policy(...).",
            )
        ]
    )
    assert views == [
        {
            "code": "LUMV0820",
            "message": "LUMV0820 happened",
            "severity": "advisory",
            "engine_severity": "error",
            "subject": {"kind": "slot", "id": "slot_account_logo"},
            "hint": "Set one with #slot:key image_policy(...).",
        }
    ]


def test_advisory_set_stays_deliberately_small() -> None:
    """A tripwire, not a style rule. The advisory set is the one place where
    an export stops being refused, so growth in it should be a conscious edit
    that updates this test — never a drive-by addition."""
    assert ADVISORY_EXPORT_DIAGNOSTIC_CODES == frozenset({"LUMV0820"})
