"""Tenant scoping for claim reads — the isolation boundary (M2.5).

The claim store stays a **single shared substrate** (conventions §2) while honouring multi-tenancy:
the tenant dimension is a *filter on the read*, not a fork of the store. :class:`WorkspaceScope` is
that filter — a value object every claim read takes, which renders to a SQL predicate over the M2.5
``reuse_scope`` / ``workspace_id`` columns:

* :meth:`WorkspaceScope.for_workspace` — public-footprint (any workspace) ∪ *this* workspace's
  private; the
  normal tenant-facing read. Never returns another tenant's private claim.
* :meth:`WorkspaceScope.public_only` — only public-footprint claims; the fail-safe default for the
  current-truth reads (it can never leak private data).
* :meth:`WorkspaceScope.all_workspaces` — no filter; the privileged audit / DSAR / operator path.

Disabling cross-tenant reuse is a *classifier* setting (``ReusePolicy.enabled`` in M2.5's identity
layer), which marks every new claim ``tenant_private`` at write — so isolation then holds by
construction and ``for_workspace`` naturally returns only the workspace's own claims. The scope here
does
not need a separate toggle.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class _ScopeMode(StrEnum):
    PUBLIC_ONLY = "public_only"
    WORKSPACE = "workspace"
    ALL = "all"
    PRIVATE_ONLY = "private_only"
    PRIVATE_FOR_WORKSPACE = "private_for_workspace"


class WorkspaceScope(BaseModel):
    """A tenant read filter. Construct via :meth:`for_workspace` / :meth:`public_only` /
    :meth:`all_workspaces`; pass to any claim read to scope it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: _ScopeMode
    workspace_id: str | None = None

    @classmethod
    def public_only(cls) -> WorkspaceScope:
        """Only public-footprint claims (the fail-safe current-truth default; leaks no private)."""
        return cls(mode=_ScopeMode.PUBLIC_ONLY)

    @classmethod
    def for_workspace(cls, workspace_id: str) -> WorkspaceScope:
        """Public-footprint ∪ ``workspace_id``'s private claims (the tenant-facing read)."""
        return cls(mode=_ScopeMode.WORKSPACE, workspace_id=workspace_id)

    @classmethod
    def all_workspaces(cls) -> WorkspaceScope:
        """No tenant filter — the privileged audit / DSAR / operator path (sees every tenant)."""
        return cls(mode=_ScopeMode.ALL)

    @classmethod
    def private_only(cls) -> WorkspaceScope:
        """Only ``tenant_private`` claims (across *all* tenants) — an operator/maintenance scope.
        A DSAR/erasure request is for one data controller, so use :meth:`private_for_workspace`."""
        return cls(mode=_ScopeMode.PRIVATE_ONLY)

    @classmethod
    def private_for_workspace(cls, workspace_id: str) -> WorkspaceScope:
        """Only *this tenant's* ``tenant_private`` claims — the DSAR/erasure selector (the data
        subject's set for one controller; never another tenant's private data). M2.5 ships the
        selector, M10.5 owns the tombstoning."""
        return cls(mode=_ScopeMode.PRIVATE_FOR_WORKSPACE, workspace_id=workspace_id)

    def predicate(self) -> tuple[str, dict[str, object]]:
        """Render to a ``(sql_fragment, params)`` pair (``sql_fragment`` is always a boolean expr).

        The param name ``scope_workspace`` is reserved; callers must not reuse it in the same query.
        """
        if self.mode is _ScopeMode.ALL:
            return "TRUE", {}
        if self.mode is _ScopeMode.PUBLIC_ONLY:
            return "reuse_scope = 'public_footprint'", {}
        if self.mode is _ScopeMode.PRIVATE_ONLY:
            return "reuse_scope = 'tenant_private'", {}
        if self.mode is _ScopeMode.PRIVATE_FOR_WORKSPACE:
            return (
                "(reuse_scope = 'tenant_private' AND workspace_id = :scope_workspace)",
                {"scope_workspace": self.workspace_id},
            )
        return (
            "(reuse_scope = 'public_footprint' OR workspace_id = :scope_workspace)",
            {"scope_workspace": self.workspace_id},
        )


# The fail-safe default for the current-truth reads (current_value / current_values /
# provenance_index): a forgotten scope returns only the shared public base — never a private claim.
PUBLIC_ONLY = WorkspaceScope.public_only()
# The default for the raw audit reader (claims_for): the operator/DSAR path sees every tenant.
ALL_WORKSPACES = WorkspaceScope.all_workspaces()
