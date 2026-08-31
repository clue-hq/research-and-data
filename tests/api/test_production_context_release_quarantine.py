from __future__ import annotations

import ast
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "tests/fixtures/production_context/release_broad_quarantine.json"
SCRIPT = REPO_ROOT / "scripts/19_production_context_release_gate.py"


def _load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("production_context_release_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_junit(path: Path, nodeids: set[str]) -> None:
    suite = ET.Element("testsuite", failures=str(len(nodeids)), tests=str(len(nodeids)))
    for nodeid in sorted(nodeids):
        file_part, *test_parts = nodeid.split("::")
        module = file_part.removesuffix(".py").replace("/", ".")
        *classes, name = test_parts
        classname = ".".join((module, *classes))
        case = ET.SubElement(suite, "testcase", classname=classname, name=name)
        ET.SubElement(case, "failure", message="reviewed failure")
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def test_release_quarantine_is_owned_exact_and_resolvable() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1"
    assert payload["scope"] == "production-deepagent-context-s3-s6-broad-backend-gate"

    nodeids: list[str] = []
    for group in payload["groups"]:
        assert group["id"]
        assert group["owner"]
        assert group["reason"]
        assert group["removal_condition"]
        assert group["nodeids"]
        nodeids.extend(group["nodeids"])

    assert len(nodeids) == 32
    assert len(nodeids) == len(set(nodeids))
    for nodeid in nodeids:
        file_part, _, function_part = nodeid.partition("::")
        test_file = REPO_ROOT / file_part
        assert test_file.is_file(), nodeid
        tree = ast.parse(test_file.read_text(encoding="utf-8"))
        functions = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert function_part in functions, nodeid


def test_release_gate_requires_the_exact_reviewed_failure_set(tmp_path: Path) -> None:
    gate = _load_gate()
    expected = set(gate.load_expected_nodeids(MANIFEST))
    exact_junit = tmp_path / "exact.xml"
    _write_junit(exact_junit, expected)

    exact = gate.compare_quarantine(manifest=MANIFEST, junit=exact_junit)
    assert exact.exact
    assert not exact.added
    assert not exact.removed

    changed = set(expected)
    repaired = changed.pop()
    changed.add("tests/api/test_production_context_release_quarantine.py::invented_regression")
    changed_junit = tmp_path / "changed.xml"
    _write_junit(changed_junit, changed)

    comparison = gate.compare_quarantine(manifest=MANIFEST, junit=changed_junit)
    assert not comparison.exact
    assert comparison.added == {
        "tests/api/test_production_context_release_quarantine.py::invented_regression"
    }
    assert comparison.removed == {repaired}
