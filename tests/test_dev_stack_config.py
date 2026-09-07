"""Check the local stack's process configuration without starting services."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("workspace_root", [None, "/tmp/clue setup/workspaces"])
def test_agent_workspace_root_reaches_platform_processes(workspace_root):
    script_path = Path(__file__).resolve().parents[1] / "scripts/dev_stack.sh"
    # Load the actual configuration functions, stopping before process helpers.
    definitions = script_path.read_text().split("\nlog_path()", 1)[0]
    env = {key: value for key, value in os.environ.items() if not key.startswith("CLUE_")}
    if workspace_root is not None:
        env["CLUE_AGENT_WORKSPACE_ROOT"] = workspace_root
    result = subprocess.run(
        [
            "bash",
            "-c",
            definitions + '\nresolve_config\nprintf "%s\\n" "${PLATFORM_ENV[@]}"\n',
            str(script_path),
        ],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    expected = workspace_root or "/private/tmp/clue-agent-workspaces"
    assert f"CLUE_AGENT_WORKSPACE_ROOT={expected}" in result.stdout.splitlines()
