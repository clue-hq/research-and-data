"""The contract-v1 Zod oracle, as a helper any suite can call.

The frontend's own accounts models (``apps/frontend/src/features/accounts/model/*.ts``) are the
*presentation truth* of contract v1, and the only way to prove a served payload really satisfies
them is to run that parser over it. This module owns the toolchain probe and the subprocess call so
the parity suite (``test_contract_v1.py``) and the endpoint suites (the ``?contract=v1`` halves of
the ``test_frontend_read_*`` files) run *identical* checks rather than two hand-rolled
approximations.

``validate.ts`` imports those models directly — the D4 re-lift retired the vendored ``zod/`` copy —
and ``zod``/``tsx`` are resolved from ``apps/frontend/node_modules`` through ``NODE_PATH``; see
``README.md`` for the incantation and the ``CLUE_DUMMY_FRONTEND_ROOT`` override (kept as the escape
hatch for pointing the runner at another checkout). Every entry point ``skip``s, naming exactly what
is missing, when that toolchain is absent, so a machine without Node still runs every pydantic-side
assertion.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_VALIDATE_TS = _HERE / "validate.ts"

DEFAULT_NODE_ROOT = str(_REPO_ROOT / "apps" / "frontend")


def node_root() -> Path:
    """The npm project whose ``node_modules`` supplies ``zod`` and ``tsx``."""
    return Path(os.environ.get("CLUE_DUMMY_FRONTEND_ROOT", DEFAULT_NODE_ROOT))


def require_node() -> Path:
    """The Node root, or ``skip`` naming exactly what is missing."""
    if shutil.which("node") is None:
        pytest.skip("the Zod oracle needs `node` on PATH; not installed here")
    root = node_root()
    if not (root / "node_modules" / "zod").is_dir():
        pytest.skip(
            f"the Zod oracle needs zod at {root}/node_modules/zod; run `npm install` in "
            "apps/frontend, or set CLUE_DUMMY_FRONTEND_ROOT "
            "(see tests/api/contract_v1/README.md)"
        )
    return root


def run_validate(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, NODE_PATH=str(root / "node_modules"))
    return subprocess.run(
        ["npx", "--prefix", str(root), "tsx", str(_VALIDATE_TS), *args],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        env=env,
        check=False,
    )


def zod_validate(payload: Any, schema_name: str) -> None:
    """Parse ``payload`` with the vendored ``schema_name``; fail the test on rejection.

    Skips (rather than passes) when the Node toolchain is unavailable, so a green run on a machine
    without it never claims the Zod half ran.
    """
    root = require_node()
    with tempfile.TemporaryDirectory() as directory:
        payload_file = Path(directory) / f"{schema_name}.json"
        payload_file.write_text(json.dumps(payload))
        result = run_validate(root, str(payload_file), schema_name)
    assert result.returncode == 0, f"{schema_name} rejected the payload:\n{result.stderr}"
