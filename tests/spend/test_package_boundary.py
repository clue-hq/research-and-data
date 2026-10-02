"""clue_spend is the shared home of the provider-caller seam (lane 3 slice 5, parent §5.4 (a)).

It may depend on clue_core/clue_obs/clue_storage and SQLAlchemy; it never imports clue_api,
clue_research or clue_projections, so the design subsystem can import it.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "libs" / "clue-spend" / "clue_spend"
FORBIDDEN = ("clue_api", "clue_research", "clue_projections", "lumen_api", "lumen_agent")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("path", sorted(PACKAGE.rglob("*.py")), ids=lambda p: p.name)
def test_no_platform_internals(path: Path) -> None:
    offenders = [name for name in _imports(path) if name.split(".")[0] in FORBIDDEN]
    assert not offenders, f"{path.name} imports platform internals: {offenders}"


def test_public_surface() -> None:
    module = importlib.import_module("clue_spend")
    for name in (
        "ProviderCaller",
        "CallSpec",
        "CallCost",
        "CallResult",
        "SpendEstimate",
        "Ceilings",
        "ProviderHalted",
        "RawSink",
        "LedgerSink",
        "MemoryRawSink",
        "MemoryLedger",
        "BufferedRawSink",
        "BufferedLedger",
        "LedgerRow",
        "LedgerStamp",
        "DrainReport",
        "drain_provider_calls",
        "ledger_id_for",
        "HttpRequest",
        "HttpResponse",
        "Transport",
        "HttpxTransport",
        "openrouter_cost_reader",
        "openrouter_halt_rule",
    ):
        assert hasattr(module, name), name


def test_arv2_names_still_resolve_to_the_shared_classes() -> None:
    from clue_api.arv2 import calls as arv2_calls
    from clue_spend import ProviderCaller

    assert arv2_calls.ProviderCaller is ProviderCaller
