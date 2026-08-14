"""Provider-free C4 receipt, dependency, and recovery-boundary guards."""

from __future__ import annotations

import ast
from pathlib import Path

from clue_research.official_site import sanitize_provider_receipt

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_receipt_sanitizer_is_recursive_bounded_and_body_free() -> None:
    receipt = {
        "request_id": "safe",
        "authorization": "secret",
        "request_headers": {"x-api-token": "secret"},
        "nested": {"raw_response": "secret", "credits_used": 1},
        "response_body": "secret",
        "large": "x" * 2_000,
    }
    assert sanitize_provider_receipt(receipt) == {
        "large": "x" * 1_000,
        "nested": {"credits_used": 1},
        "request_id": "safe",
    }
    huge = {f"field_{index}": "x" * 2_000 for index in range(50)}
    assert sanitize_provider_receipt(huge) == {"receipt_omitted": "sanitized_size_limit"}


def test_recovery_modules_do_not_import_or_branch_on_provider_packages() -> None:
    for relative in (
        "subsystems/research/clue_research/official_site/artifacts.py",
        "subsystems/research/clue_research/official_site/reconciliation.py",
    ):
        source = (_REPO_ROOT / relative).read_text()
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        assert not any(
            provider in imported for imported in imports for provider in ("firecrawl", "scrapling")
        )
        string_literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert "firecrawl" not in string_literals
        assert "scrapling" not in string_literals
