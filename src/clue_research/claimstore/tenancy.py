"""Tenant scoping for claim reads — the isolation boundary (M2.5).

The claim store stays a **single shared substrate** (conventions §2) while honouring multi-tenancy:
the tenant dimension is a *filter on the read*, not a fork of the store. :class:`TenantScope` is
that filter — a value object every claim read takes, which renders to a SQL predicate over the M2.5
``reuse_scope`` / ``tenant_id`` columns:

* :meth:`TenantScope.for_tenant` — public-footprint (any tenant) ∪ *this* tenant's private; the
  normal tenant-facing read. Never returns another tenant's private claim.
* :meth:`TenantScope.public_only` — only public-footprint claims; the fail-safe default for the
  current-truth reads (it can never leak private data).
* :meth:`TenantScope.all_tenants` — no filter; the privileged audit / DSAR / operator path.

Disabling cross-tenant reuse is a *classifier* setting (``ReusePolicy.enabled`` in M2.5's identity
layer), which marks every new claim ``tenant_private`` at write — so isolation then holds by
construction and ``for_tenant`` naturally returns only the tenant's own claims. The scope here does
not need a separate toggle.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class _ScopeMode(StrEnum):
    PUBLIC_ONLY = "public_only"
    TENANT = "tenant"
    ALL = "all"
    PRIVATE_ONLY = "private_only"


class TenantScope(BaseModel):
    """A tenant read filter. Construct via :meth:`for_tenant` / :meth:`public_only` /
    :meth:`all_tenants`; pass to any claim read to scope it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: _ScopeMode
    tenant_id: str | None = None

    @classmethod
    def public_only(cls) -> TenantScope:
        """Only public-footprint claims (the fail-safe current-truth default; leaks no private)."""
        return cls(mode=_ScopeMode.PUBLIC_ONLY)

    @classmethod
    def for_tenant(cls, tenant_id: str) -> TenantScope:
        """Public-footprint ∪ ``tenant_id``'s private claims (the tenant-facing read)."""
        return cls(mode=_ScopeMode.TENANT, tenant_id=tenant_id)

    @classmethod
    def all_tenants(cls) -> TenantScope:
        """No tenant filter — the privileged audit / DSAR / operator path (sees every tenant)."""
        return cls(mode=_ScopeMode.ALL)

    @classmethod
    def private_only(cls) -> TenantScope:
        """Only ``tenant_private`` claims — the DSAR/erasure selector (the data subject's set; M2.5
        ships the selector, M10.5 owns the tombstoning)."""
        return cls(mode=_ScopeMode.PRIVATE_ONLY)

    def predicate(self) -> tuple[str, dict[str, object]]:
        """Render to a ``(sql_fragment, params)`` pair (``sql_fragment`` is always a boolean expr).

        The param name ``scope_tenant`` is reserved; callers must not reuse it in the same query.
        """
        if self.mode is _ScopeMode.ALL:
            return "TRUE", {}
        if self.mode is _ScopeMode.PUBLIC_ONLY:
            return "reuse_scope = 'public_footprint'", {}
        if self.mode is _ScopeMode.PRIVATE_ONLY:
            return "reuse_scope = 'tenant_private'", {}
        return (
            "(reuse_scope = 'public_footprint' OR tenant_id = :scope_tenant)",
            {"scope_tenant": self.tenant_id},
        )


# The fail-safe default for the current-truth reads (current_value / current_values /
# provenance_index): a forgotten scope returns only the shared public base — never a private claim.
PUBLIC_ONLY = TenantScope.public_only()
# The default for the raw audit reader (claims_for): the operator/DSAR path sees every tenant.
ALL_TENANTS = TenantScope.all_tenants()
