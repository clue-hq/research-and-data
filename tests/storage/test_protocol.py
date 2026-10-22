"""Storage key shapes — the namespaces that keep one kind of blob out of another's cleanup."""

from __future__ import annotations

from clue_storage import agent_workspace_key, artifact_key, is_agent_workspace_key

_SHA = "ab" * 32


def test_agent_workspace_key_has_its_own_area() -> None:
    assert agent_workspace_key("ws_a", _SHA) == f"ws_a/agent-workspace/{_SHA}"
    assert is_agent_workspace_key(f"ws_a/agent-workspace/{_SHA}")
    assert not is_agent_workspace_key(artifact_key("ws_a", _SHA))
    assert not is_agent_workspace_key(f"ws_a/design/{_SHA}")
