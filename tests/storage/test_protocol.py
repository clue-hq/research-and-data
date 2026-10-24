"""Storage key shapes — the namespaces that keep one kind of blob out of another's cleanup."""

from __future__ import annotations

import pytest

from clue_storage import agent_workspace_key, artifact_key, is_agent_workspace_key

_SHA = "ab" * 32


def test_agent_workspace_key_has_its_own_area() -> None:
    assert agent_workspace_key("ws_a", _SHA) == f"ws_a/agent-workspace/{_SHA}"
    assert is_agent_workspace_key(f"ws_a/agent-workspace/{_SHA}")
    assert not is_agent_workspace_key(artifact_key("ws_a", _SHA))
    assert not is_agent_workspace_key(f"ws_a/design/{_SHA}")


@pytest.mark.parametrize(
    "storage_key",
    [
        f"ws/x/agent-workspace/{_SHA}",  # the segment one level too deep
        f"agent-workspace/ws/{_SHA}",  # the segment first, not second
        f"ws/agent-workspace-old/{_SHA}",  # a segment that only starts with the name
        f"ws/agent-workspace/{_SHA}/extra",  # a fourth segment after the hash
        f"ws/agent-workspace/{_SHA}/",  # a trailing slash
        f"ws/agent-workspace{_SHA}",  # the name run into the hash
        "ws/agent-workspace",  # no hash at all
        "agent-workspace",
    ],
)
def test_a_key_merely_containing_the_area_name_is_not_in_the_area(storage_key: str) -> None:
    """Review area 1, T2: this answer decides what the retention sweep may DELETE, so it is the
    exact three-segment shape ``agent_workspace_key`` writes and never a substring match. Each key
    here contains the word; none of them is in the area."""

    assert not is_agent_workspace_key(storage_key)


@pytest.mark.parametrize("scope", ["ws", "ws_a", "public"])
def test_the_exact_three_segment_shape_is_in_the_area(scope: str) -> None:
    assert is_agent_workspace_key(f"{scope}/agent-workspace/{_SHA}")
    assert is_agent_workspace_key(agent_workspace_key(None if scope == "public" else scope, _SHA))
