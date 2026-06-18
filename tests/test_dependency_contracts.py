"""M0.1 acceptance: the modular-boundary rules are declared and actually pass.

The import-linter contracts are the executable form of conventions §2. Here we (a) assert the five
rules are present so they can't be silently deleted, and (b) run import-linter to prove the current
tree satisfies them. Negative/regression tests (deliberately introduce a violation and assert the
build fails) land with the full test harness in M0.6.
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _contracts() -> list[dict]:
    data = tomllib.loads((REPO / "pyproject.toml").read_text())
    return data["tool"]["importlinter"]["contracts"]


def test_five_modular_boundary_rules_are_declared() -> None:
    contracts = _contracts()
    names = [c["name"].lower() for c in contracts]
    types = {c["type"] for c in contracts}

    assert {"forbidden", "layers", "independence"} <= types
    assert any("kernel" in n for n in names), "missing: core imports nothing internal"
    assert any("workers are independent" in n for n in names), "missing: workers independence"
    assert any("provider sdk" in n for n in names), "missing: no provider-SDK leakage"
    assert any("api app layer" in n for n in names), "missing: nothing imports api/"


def test_provider_sdk_rule_exempts_only_resolvers_and_adapters() -> None:
    contracts = _contracts()
    sdk = next(c for c in contracts if "provider sdk" in c["name"].lower())
    sources = set(sdk["source_modules"])
    # resolvers/ and adapters/ are the ONLY packages allowed to import a provider SDK.
    assert "clue_research.resolvers" not in sources
    assert "clue_research.adapters" not in sources
    assert "firecrawl" in sdk["forbidden_modules"]


def test_import_contracts_currently_pass() -> None:
    exe = shutil.which("lint-imports")
    if exe is None:
        pytest.skip("import-linter not installed in this environment")
    result = subprocess.run([exe], cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, f"import-linter failed:\n{result.stdout}\n{result.stderr}"
