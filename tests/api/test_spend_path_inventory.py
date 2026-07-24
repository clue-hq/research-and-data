"""Static C0 guard: every production claim-producing spend path is classified."""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_RESEARCH = _ROOT / "subsystems/research/clue_research"

_GATED_CALLS = {
    ("coverage/controller.py", "run_round", "resolve_field"): "source_gate",
    (
        "discovery_scoring/scoring/engine.py",
        "score_account",
        "resolve_fields",
    ): "source_gate_factory",
    ("profiling/aspect_worker.py", "_fill_field", "resolve_field"): "source_gate",
    ("profiling/contact/fill.py", "fill_contact_field", "resolve_field"): "source_gate",
    ("sources/waterfall.py", "resolve_fields", "resolve_field"): "source_gate",
    ("stage0/client_kb.py", "reverse_profile", "resolve_field"): "source_gate",
    ("stage0/import_accounts.py", "_crm_enrich", "resolve_field"): "source_gate",
}


def _production_waterfall_calls() -> dict[tuple[str, str, str], set[str]]:
    calls: dict[tuple[str, str, str], set[str]] = {}
    for path in sorted(_RESEARCH.rglob("*.py")):
        tree = ast.parse(path.read_text())
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"resolve_field", "resolve_fields"}
            ):
                continue
            owner: ast.AST | None = node
            while owner is not None and not isinstance(
                owner, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                owner = parents.get(owner)
            assert isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef))
            key = (
                str(path.relative_to(_RESEARCH)),
                owner.name,
                node.func.id,
            )
            calls[key] = {kw.arg for kw in node.keywords if kw.arg is not None}
    return calls


def test_every_production_waterfall_caller_is_gated() -> None:
    calls = _production_waterfall_calls()
    assert set(calls) == set(_GATED_CALLS)
    for call, gate_keyword in _GATED_CALLS.items():
        assert gate_keyword in calls[call], f"{call} lost its pre-spend routing"


def test_paid_ingestion_adapter_gate_precedes_extraction() -> None:
    path = _RESEARCH / "ingestion/engine.py"
    tree = ast.parse(path.read_text())
    normalize = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "IngestionEngine"
        for node in node.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_normalize"
    )
    gate_call = next(
        node
        for node in ast.walk(normalize)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_source_gate"
    )
    extraction_call = next(
        node
        for node in ast.walk(normalize)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "extract"
    )
    assert gate_call.lineno < extraction_call.lineno
