"""Run or inspect the S3-S6 broad backend gate against its exact reviewed quarantine.

This is deliberately not a pytest skip list. The broad suite still runs every test. The gate
accepts only the exact reviewed failure set, so a new regression or a repaired-but-still-listed
test both fail closed until the manifest is reviewed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    REPO_ROOT / "tests/fixtures/production_context/release_broad_quarantine.json"
)


@dataclass(frozen=True)
class QuarantineComparison:
    expected: frozenset[str]
    observed: frozenset[str]

    @property
    def added(self) -> frozenset[str]:
        return self.observed - self.expected

    @property
    def removed(self) -> frozenset[str]:
        return self.expected - self.observed

    @property
    def exact(self) -> bool:
        return not self.added and not self.removed


def load_expected_nodeids(path: Path) -> frozenset[str]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    groups = payload.get("groups")
    if payload.get("schema_version") != "1" or not isinstance(groups, list):
        raise ValueError("unsupported or malformed quarantine manifest")
    nodeids = [nodeid for group in groups for nodeid in group.get("nodeids", [])]
    if not nodeids or len(nodeids) != len(set(nodeids)):
        raise ValueError("quarantine nodeids must be non-empty and unique")
    return frozenset(nodeids)


def _nodeid_from_case(case: ET.Element) -> str:
    classname = case.attrib.get("classname", "")
    name = case.attrib.get("name", "")
    if not classname or not name:
        raise ValueError("JUnit failure is missing classname or name")

    parts = classname.split(".")
    for split_at in range(len(parts), 0, -1):
        candidate = REPO_ROOT.joinpath(*parts[:split_at]).with_suffix(".py")
        if candidate.is_file():
            path = candidate.relative_to(REPO_ROOT).as_posix()
            class_parts = parts[split_at:]
            suffix = "::".join((*class_parts, name))
            return f"{path}::{suffix}"
    raise ValueError(f"cannot resolve JUnit classname to a test file: {classname}")


def parse_junit_failures(path: Path) -> frozenset[str]:
    root = ET.parse(path).getroot()
    failures: set[str] = set()
    for case in root.iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            failures.add(_nodeid_from_case(case))
    return frozenset(failures)


def compare_quarantine(*, manifest: Path, junit: Path) -> QuarantineComparison:
    return QuarantineComparison(
        expected=load_expected_nodeids(manifest),
        observed=parse_junit_failures(junit),
    )


def _print_comparison(comparison: QuarantineComparison) -> None:
    if comparison.added:
        print("NEW UNREVIEWED FAILURES:")
        for nodeid in sorted(comparison.added):
            print(f"  + {nodeid}")
    if comparison.removed:
        print("REPAIRED OR UNOBSERVED QUARANTINE ENTRIES:")
        for nodeid in sorted(comparison.removed):
            print(f"  - {nodeid}")
    if comparison.exact:
        print(f"exact reviewed quarantine observed: {len(comparison.observed)} failures")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--junit", type=Path, help="inspect an existing pytest JUnit XML file")
    source.add_argument(
        "--run",
        action="store_true",
        help="run the broad pytest suite and compare its JUnit result",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="pytest arguments after -- when --run is used (defaults to tests)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    junit = args.junit
    pytest_returncode: int | None = None

    if args.run:
        pytest_args = list(args.pytest_args)
        if pytest_args[:1] == ["--"]:
            pytest_args = pytest_args[1:]
        if not pytest_args:
            pytest_args = ["tests"]
        with tempfile.TemporaryDirectory(prefix="clue-context-release-") as temp_dir:
            junit = Path(temp_dir) / "broad-suite.xml"
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", f"--junitxml={junit}", *pytest_args],
                cwd=REPO_ROOT,
                check=False,
            )
            pytest_returncode = completed.returncode
            if pytest_returncode not in {0, 1}:
                print(
                    f"pytest did not complete normally (exit {pytest_returncode})",
                    file=sys.stderr,
                )
                return 2
            comparison = compare_quarantine(manifest=args.manifest, junit=junit)
    else:
        assert junit is not None
        comparison = compare_quarantine(manifest=args.manifest, junit=junit)

    _print_comparison(comparison)
    if not comparison.exact:
        return 1
    if pytest_returncode == 0:
        print("pytest was green; remove the obsolete quarantine manifest", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
