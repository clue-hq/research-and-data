"""Per-run context the M8 deep workers need but ``AspectContext`` does not yet carry.

The M7 graph hands an :class:`~clue_research.core.AspectContext` to each worker with the entity, the
run id, the tier, the aspect's gap ``field_keys``, the budget envelope, and the recursion soft-cap —
but **not** the campaign's ``client_id`` / ``icp`` coordinates or its ``tenant_id``. A deep worker
needs those to (a) load the active :class:`~clue_research.core.ICPSpec` for the Source Planner and
(b) write a ``tenant_private`` claim (``account.resonance.*`` is tenant-private — the M4 waterfall
fails *loud* without a ``tenant_id``).

`AspectContext.params` is the frozen escape hatch for exactly this (its docstring: "the escape hatch
for phase-specific inputs … so adding one does not force a ``core`` change"). M7.1 ships it carrying
only ``{"recursion": {...}}`` today; the **api composition root** populates the campaign coordinates
when it builds the per-account graph run (``api/composition.py`` / ``api/deep/composition.py``).
:class:`RunContext` reads them defensively: every field is optional and the worker degrades to a
correct, *flagged* output (never a crash) when a coordinate is absent — the same fail-soft discipline
as the M9.1 / M9.4 deferred gate wirings.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue

from clue_research.claimstore import PUBLIC_ONLY, TenantScope

# The `AspectContext.params` keys the api root populates (mirrors the durable graph's `recursion`
# key). Kept here so the producer (api/composition.py) and consumer (the worker) name them once.
PARAM_CLIENT_ID = "client_id"
PARAM_ICP_KEY = "icp_key"
PARAM_ICP_VERSION = "icp_version"
PARAM_TENANT_ID = "tenant_id"


def _opt_str(value: JsonValue | None) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _opt_int(value: JsonValue | None) -> int | None:
    if isinstance(value, bool):  # bool is an int subclass — never an icp_version
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


class RunContext(BaseModel):
    """The campaign coordinates a deep worker reads out of ``AspectContext.params`` (M8).

    All optional: a worker invoked outside a wired graph (a unit test, or the api root before the
    deferred params wiring lands) still runs — it just falls back to the field's own ``tier_plan``
    (no planner) and refuses to write a ``tenant_private`` field (no ``tenant_id``), leaving it
    empty/flagged. ``tenant_id`` defaults to ``client_id`` (a campaign's tenant *is* its client; the
    project's ``tenant_id`` vs ``client_id`` naming is the same concept — see the M2/M3
    harmonisation note in CLAUDE.md)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_id: str | None = None
    icp_key: str | None = None
    icp_version: int | None = None
    tenant_id: str | None = None

    @classmethod
    def from_params(cls, params: dict[str, JsonValue]) -> RunContext:
        """Read the campaign coordinates out of ``AspectContext.params`` (defensive — never
        raises)."""
        client_id = _opt_str(params.get(PARAM_CLIENT_ID))
        return cls(
            client_id=client_id,
            icp_key=_opt_str(params.get(PARAM_ICP_KEY)),
            icp_version=_opt_int(params.get(PARAM_ICP_VERSION)),
            # A campaign's tenant is its client; fall back to client_id when not separately set.
            tenant_id=_opt_str(params.get(PARAM_TENANT_ID)) or client_id,
        )

    @property
    def has_icp(self) -> bool:
        """Whether the full ICP coordinate is present (so the Source Planner can load the spec)."""
        return (
            self.client_id is not None and self.icp_key is not None and self.icp_version is not None
        )

    def tenant_scope(self) -> TenantScope:
        """The merge/read scope for this run: the tenant's view (public ∪ its private) when a tenant
        is known, else the public base only — so a worker never reads another tenant's private claim
        and a tenant-less run sees only public truth."""
        return TenantScope.for_tenant(self.tenant_id) if self.tenant_id is not None else PUBLIC_ONLY


def params_for_run(
    *,
    client_id: str | None,
    icp_key: str | None,
    icp_version: int | None,
    tenant_id: str | None = None,
) -> dict[str, JsonValue]:
    """Build the ``AspectContext.params`` campaign-coordinate dict (the producer side).

    Called by the api composition root (``api/composition.py``, ``api/deep/composition.py``) and by
    ``profile_account`` for its per-aspect contexts so the keys are written in exactly one place.
    Omits ``None`` values so the
    dict round-trips cleanly through the graph's JSON state."""
    raw: dict[str, JsonValue | None] = {
        PARAM_CLIENT_ID: client_id,
        PARAM_ICP_KEY: icp_key,
        PARAM_ICP_VERSION: icp_version,
        PARAM_TENANT_ID: tenant_id if tenant_id is not None else client_id,
    }
    return {k: v for k, v in raw.items() if v is not None}


__all__ = [
    "RunContext",
    "params_for_run",
    "PARAM_CLIENT_ID",
    "PARAM_ICP_KEY",
    "PARAM_ICP_VERSION",
    "PARAM_TENANT_ID",
]
