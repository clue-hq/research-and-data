"""Check the local stack's process configuration without starting services."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("workspace_root", [None, "/tmp/clue setup/workspaces"])
def test_agent_workspace_root_reaches_platform_processes(workspace_root):
    """A CLUE_AGENT_WORKSPACE_ROOT already in the shell reaches PLATFORM_ENV (no DEV_STACK_*
    wrapper needed); with nothing set the historical default is used."""
    script_path = Path(__file__).resolve().parents[1] / "scripts/dev_stack.sh"
    # Load only the top-level configuration assignments, stopping before the first function.
    definitions = script_path.read_text().split("\nload_env()", 1)[0]
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CLUE_", "DEV_STACK_"))
    }
    if workspace_root is not None:
        env["CLUE_AGENT_WORKSPACE_ROOT"] = workspace_root
    result = subprocess.run(
        [
            "bash",
            "-c",
            definitions + '\nprintf "%s\\n" "${PLATFORM_ENV[@]}"\n',
            str(script_path),
        ],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    expected = workspace_root or "/private/tmp/clue-agent-workspaces"
    assert f"CLUE_AGENT_WORKSPACE_ROOT={expected}" in result.stdout.splitlines()


def _top_level(tmp_path: Path, env_file: str | None, extra_env: dict[str, str]) -> list[str]:
    """Run the script's top-level settings as if the checkout were `tmp_path` (whose `.env`
    the test writes), and return PAGES_PORT followed by PLATFORM_ENV."""
    script_path = Path(__file__).resolve().parents[1] / "scripts/dev_stack.sh"
    definitions = script_path.read_text().split("\nload_env()", 1)[0]
    (tmp_path / "scripts").mkdir()
    if env_file is not None:
        (tmp_path / ".env").write_text(env_file)
    env = {key: value for key, value in os.environ.items() if not key.startswith(("CLUE_", "DEV_STACK_"))}
    env.update(extra_env)
    result = subprocess.run(
        ["bash", "-c", definitions + '\nprintf "%s\\n" "$PAGES_PORT" "${PLATFORM_ENV[@]}"\n',
         str(tmp_path / "scripts" / "dev_stack.sh")],
        env=env, text=True, capture_output=True, check=True,
    )
    return result.stdout.splitlines()


@pytest.mark.parametrize(
    ("env_file", "extra_env", "expected"),
    [
        ("CLUE_PAGES_ORIGIN_PORT=8049\n", {}, "8049"),  # the lane's own page-origin port (trenton)
        ('CLUE_PAGES_ORIGIN_PORT="8049"\n', {}, "8049"),
        ("CLUE_PAGES_SYSTEM_SUFFIX=pages.cluehq.ai\n", {}, "8040"),  # no key: the runbook port
        (None, {}, "8040"),
        ("CLUE_PAGES_ORIGIN_PORT=8049\n", {"DEV_STACK_PAGES_PORT": "8177"}, "8177"),  # the knob wins
    ],
)
def test_the_page_origin_runs_on_the_checkouts_own_port(tmp_path, env_file, extra_env, expected):
    """Every lane names its page-origin port in .env (CLUE_PAGES_ORIGIN_PORT); the stack starts the
    page origin there and tells the APIs the same public port, so page links point at THIS lane's
    page origin — never at another lane's on 8040."""
    lines = _top_level(tmp_path, env_file, extra_env)
    assert lines[0] == expected
    assert f"CLUE_PAGES_PUBLIC_PORT={expected}" in lines[1:]


def test_no_page_origin_command_hard_codes_8040():
    """Start, status and the restart wait all use $PAGES_PORT; 8040 survives only as the default."""
    script = (Path(__file__).resolve().parents[1] / "scripts/dev_stack.sh").read_text()
    code_lines = [line for line in script.splitlines() if "8040" in line and not line.lstrip().startswith("#")]
    assert code_lines == ['PAGES_PORT="${PAGES_PORT:-8040}"'], code_lines
