"""Every file a research launch manifest pins is committed, with the pinned bytes.

A launch recipe (platform/agents/catalog/research-quality/launch-*.json) names each skill, prompt
and profile file it runs with and its sha256. The launch reads those files from the image, which is
built from git, so a pinned file that exists only on a developer's disk ships as a launch that fails
for everyone (2026-10-13: recipe 26 pinned governed-evidence/v5/SKILL.md, which was never committed,
and every production account-research launch failed with FileNotFoundError). The check uses
`git ls-files`, so an untracked file on the local disk cannot hide the gap.
"""

import hashlib
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "platform/agents/catalog/research-quality"


def _pins(node: object, found: dict[str, str]) -> dict[str, str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str) and "/" in key and len(value) == 64 and all(c in "0123456789abcdef" for c in value):
                found[key] = value
            else:
                _pins(value, found)
    elif isinstance(node, list):
        for value in node:
            _pins(value, found)
    return found


def test_every_pinned_launch_file_is_committed_with_its_pinned_bytes() -> None:
    tracked = set(
        subprocess.run(
            ["git", "ls-files", "--", str(CATALOG.relative_to(REPO))], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.split()
    )
    manifests = sorted(CATALOG.glob("launch-*.json"))
    assert manifests, "no launch manifests found"
    problems = []
    for manifest in manifests:
        for rel, sha in _pins(json.loads(manifest.read_text()), {}).items():
            path = CATALOG / rel
            if str(path.relative_to(REPO)) not in tracked:
                problems.append(f"{manifest.name}: {rel} is not committed")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                problems.append(f"{manifest.name}: {rel} does not match its pinned sha256")
    assert not problems, "\n".join(problems)
