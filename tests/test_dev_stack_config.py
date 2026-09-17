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
