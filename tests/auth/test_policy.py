"""The MVP permission floor is internal, immutable, and monotonic by role."""

from __future__ import annotations

import pytest

from clue_auth import (
    ROLE_PERMISSIONS,
    ROLE_POLICY_VERSION,
    permissions_for_role,
    role_can_assign,
)


def test_role_policy_is_internal_and_monotonic() -> None:
    assert ROLE_POLICY_VERSION == 3
    assert set(ROLE_PERMISSIONS) == {"owner", "admin", "operator", "viewer"}
    assert ROLE_PERMISSIONS["viewer"] < ROLE_PERMISSIONS["operator"]
    assert ROLE_PERMISSIONS["operator"] < ROLE_PERMISSIONS["admin"]
    assert ROLE_PERMISSIONS["admin"] == ROLE_PERMISSIONS["owner"]
    assert "workspace.manage_members" not in ROLE_PERMISSIONS["operator"]
    assert "workspace.manage_settings" in ROLE_PERMISSIONS["admin"]
    assert "workspace.manage_settings" not in ROLE_PERMISSIONS["operator"]
    assert "workspace.manage_settings" not in ROLE_PERMISSIONS["viewer"]
    assert "project.write" not in ROLE_PERMISSIONS["viewer"]
    assert "project.write" in ROLE_PERMISSIONS["operator"]
    assert "research.approve_spend" not in ROLE_PERMISSIONS["operator"]
    assert "research.approve_spend" in ROLE_PERMISSIONS["admin"]
    assert role_can_assign("admin", "operator")
    assert not role_can_assign("admin", "owner")
    assert role_can_assign("owner", "owner")


def test_unknown_provider_authored_role_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown role_key"):
        permissions_for_role("clerk:org-admin")
