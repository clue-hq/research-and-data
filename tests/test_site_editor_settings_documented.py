"""Lane C task C11: the site editor's settings ship their defaults and the dev stack runs it."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _value(path: str, key: str) -> str | None:
    match = re.search(rf"^{key}=(.*)$", (REPO / path).read_text(encoding="utf-8"), re.MULTILINE)
    return None if match is None else match.group(1).strip()


def test_the_editor_settings_are_documented_with_their_defaults() -> None:
    assert _value(".env.example", "CLUE_SITE_EDITOR_SUFFIX") == "edit.deeppresence.ai"
    assert _value(".env.example", "DEV_STACK_EDITOR_PORT") == "3120"
    assert _value("apps/frontend/.env.example", "CLUE_SITE_EDITOR_SUFFIX") == "edit.deeppresence.ai"
    package = "apps/frontend/packages/site-editor/.env.example"
    for key in ("PORT", "HOST", "CLUE_APP_ORIGIN", "LUMEN_API_BASE_URL", "CLUE_SITE_EDITOR_SUFFIX"):
        assert _value(package, key) is not None, f"{package} does not document {key}"


def test_the_dev_stack_runs_the_editor_on_its_own_domain() -> None:
    script = (REPO / "scripts/dev_stack.sh").read_text(encoding="utf-8")
    assert 'EDITOR_PORT="${DEV_STACK_EDITOR_PORT:-3120}"' in script
    assert "start_site_editor" in script and "stop_site_editor" in script
    assert 'CLUE_SITE_EDITOR_SUFFIX="editor.localhost:${EDITOR_PORT}"' in script
    assert "restart-editor) restart_editor ;;" in script
    subprocess.run(["bash", "-n", str(REPO / "scripts/dev_stack.sh")], check=True)


def test_the_trenton_wrapper_requires_the_editor_port() -> None:
    assert "DEV_STACK_EDITOR_PORT" in (REPO / "scripts/dev_stack_trenton.sh").read_text(
        encoding="utf-8"
    )
