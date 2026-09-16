"""The initial internal role-to-permission policy (never sourced from provider claims)."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal, cast

from clue_auth.models import RoleKey

Permission = Literal[
    "project.read",
    "project.write",
    "thread.read",
    "thread.write",
    "gate.respond",
    "research.estimate",
    "research.launch",
    "research.approve_spend",
    "workspace.manage_members",
    "workspace.manage_settings",
]

# B1's initial internal policy revision. B2 resolves this version at authorization time; moving
# the mapping into data later does not change the role/permission seam. Revision 2 adds the
# founder-ratified Home-bootstrap authority: operators, admins and owners may create projects;
# viewers remain read-only. Revision 3 separates workspace settings from member management.
ROLE_POLICY_VERSION = 3

_READ: frozenset[Permission] = frozenset({"project.read", "thread.read"})
_OPERATE: frozenset[Permission] = _READ | frozenset(
    {
        "project.write",
        "thread.write",
        "gate.respond",
        "research.estimate",
        "research.launch",
    }
)
_MANAGE: frozenset[Permission] = _OPERATE | frozenset(
    {"research.approve_spend", "workspace.manage_members", "workspace.manage_settings"}
)

ROLE_PERMISSIONS: Mapping[RoleKey, frozenset[Permission]] = MappingProxyType(
    {
        "viewer": _READ,
        "operator": _OPERATE,
        "admin": _MANAGE,
        "owner": _MANAGE,
    }
)


def require_role_key(role_key: str) -> RoleKey:
    """Validate a role before issuing SQL, mirroring the migration's named CHECK."""
    if role_key not in ROLE_PERMISSIONS:
        raise ValueError(
            f"unknown role_key {role_key!r}; expected one of {tuple(ROLE_PERMISSIONS)}"
        )
    return cast(RoleKey, role_key)


def permissions_for_role(role_key: str) -> frozenset[Permission]:
    """Return the immutable internal permissions for ``role_key``."""
    return ROLE_PERMISSIONS[require_role_key(role_key)]


def role_has_permission(role_key: str, permission: Permission) -> bool:
    return permission in permissions_for_role(role_key)


def role_can_assign(actor_role: str, target_role: str) -> bool:
    """Prevent a membership administrator from granting above its own internal role."""
    actor = require_role_key(actor_role)
    target = require_role_key(target_role)
    rank: Mapping[RoleKey, int] = {"viewer": 0, "operator": 1, "admin": 2, "owner": 3}
    return role_has_permission(actor, "workspace.manage_members") and rank[target] <= rank[actor]
