"""M9.1 — the pre-spend schema/identity gate (ENG-130).

The cheapest verification is the one that prevents spend on a doomed claim (substrate §6(1)). Before
any resolver runs or any synthesis dollar is spent, a claim/research request must clear a set of
**entry gates** — the prototype's single strongest contribution: an official-domain / strong-key
requirement, a canonical-name lock, dedup-registry membership, the in-flight lock, and a
*target-locked prompt* ("this exact company, this domain — do not drift to similarly-named orgs").
This module promotes those into one declarative, config-driven gate that every claim-producing path
(the M4 waterfall, M8 workers, M11 synthesis) calls *before* it acts.

It implements the Beat-0 :class:`clue_core.verification.PreSpendGate` protocol, so
callers in other milestone packages depend only on the ``core`` seam (the impl is injected at the
``api`` composition root). Two surfaces:

* :class:`PreSpendGateImpl` — ``check(request)`` runs the schema gate (field registered, requested
  tier in the field's ``tier_plan``, ``value_json`` valid), the identity gate (the ``entity_id``
  resolves to a ``candidate``/``active`` registry row carrying a strong key — ``merged``/unresolved
  rejected), and the in-flight-lock check (reject if a *different* run holds the entity lock). Every
  decision is recorded as a ``gate_decision`` audit row and emits the
  ``verification.pre_spend_gate`` span — so "claims blocked pre-spend" is measurable (Doc C §6).
* :func:`assemble_target_lock` — builds a :class:`TargetLock` (canonical-domain ``site:`` filter +
  no-drift instruction) from a *resolved* entity, so target-lock is constructed, not hand-prompted.

The gate set is **policy-as-data** (conventions §2): :class:`PreSpendPolicy` rows live in
``pre_spend_policy`` (per-client/ICP overridable) and per-field overrides ride in the existing
``field_definition.gate`` column as a :class:`GateSpec`. Flipping a rule is a config change, not a
code change. The ``Resolver`` protocol is untouched — resolvers are gated *by the caller*.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountEntity,
    AccountStatus,
    ContactEntity,
    EffectiveFieldSourcePlan,
    EffectiveSourceAuthorization,
    EnumerationScope,
    FieldDef,
    PreSpendDecision,
    PreSpendKind,
    PreSpendRequest,
    PreSpendVerdict,
    RunId,
    SourceTier,
    TargetLock,
    serialize_value_json,
)
from clue_db import ConnFactory, transaction
from clue_locks.entity_lock import lock_key
from clue_obs.otel import (
    ATTR_ENTITY_ID,
    ATTR_ENTITY_TYPE,
    ATTR_FIELD_KEY,
    ATTR_GATE_DECISION,
    ATTR_RUN_ID,
    ATTR_SOURCE_TIER,
    SPAN_VERIFICATION_PRE_SPEND_GATE,
    MetricSink,
    apply_attributes,
    get_metric_sink,
    traced_step,
)
from clue_research.claimstore.registry import (
    UnknownFieldError,
    ValueSchemaError,
    get_field,
    validate_value,
)
from clue_research.icp import get_icp_version
from clue_research.identity import get_entity
from clue_research.sources.authority import (
    EffectiveSourcePlanConflict,
    freeze_effective_source_plan,
    load_effective_source_plan,
)
from clue_research.sources.source_profile import resolve_allowed_set

# Blocked-pre-spend counter (the "claims blocked pre-spend" verification-health signal, Doc C §6).
# An M9-local metric name (metric names are plain strings the shared sink accepts) — defined here so
# M9.1 stays self-contained and does not edit the shared obs/metrics.py.
METRIC_PRESPEND_DECISIONS = "research.verification.prespend.decisions"
METRIC_PRESPEND_BLOCKED = "research.verification.prespend.blocked"

# The two account statuses a profiling/spend request may target. ``candidate`` is discovery-only (it
# passed M6.2's existence gate but is not yet promoted to ``active``); ``merged`` redirects to
# ``merged_into`` and is never spent on.
_DEFAULT_ALLOWED_STATUSES = (AccountStatus.CANDIDATE, AccountStatus.ACTIVE)


class _LockReader(Protocol):
    """The minimal Redis surface the in-flight check needs: read the current holder token for a key.

    Typed structurally so the gate never imports the redis client type and stays trivially testable
    with a fake. ``redis.asyncio.Redis`` satisfies it (``await redis.get(key)``)."""

    async def get(self, name: str) -> object: ...


def run_lock_token(run_id: RunId) -> str:
    """The fencing token a run uses for its entity locks (the convention the in-flight check reads).

    A run that holds an entity's in-flight lock acquires it with ``entity_lock(..., token=
    run_lock_token(run_id))``; the gate then recognises *this* run's lock and rejects only a lock
    held by a *different* run (anti-double-spend). Kept a pure, stable function so the locker
    (M7/M8) and the checker (M9.1) agree without importing each other."""
    return str(run_id)


class GateSpec(BaseModel):
    """A per-field pre-spend override, carried in the existing ``field_definition.gate`` column as a
    JSON object (same column, declared contents — no schema change; M9.1). A field can demand a
    stricter gate than the global policy (e.g. a registry-keyed field that must carry an official
    domain). Non-JSON / legacy ``gate`` text (``"tier>=1"``) parses to ``None`` and is ignored."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requires_official_domain: bool | None = None
    requires_strong_key: bool | None = None


class PreSpendPolicy(BaseModel):
    """The pre-spend gate rules as data (policy-as-data, conventions §2). Persisted in
    ``pre_spend_policy`` (``rules_json``), per-client/ICP overridable; the gate reads it at
    construction. Flipping a flag changes behaviour with no code change."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Identity: the entity must carry a strong key (account ``primary_domain`` — the official-domain
    # requirement; contact LinkedIn URL / verified email). The same-name trap's structural defence.
    requires_strong_key: bool = True
    # The entity must resolve to a registry row in one of these statuses (``merged``/unresolved are
    # always rejected). Discovery-only ``candidate`` is allowed (it passed the M6.2 existence gate).
    allowed_statuses: tuple[AccountStatus, ...] = _DEFAULT_ALLOWED_STATUSES
    # Schema: the requested ``source_tier`` must be sanctioned by the field's ``tier_plan`` (the
    # plan must list a source registered at that tier). A field/tier mismatch fails closed.
    enforce_tier_in_plan: bool = True
    # Cost guard: reject if a *different* run holds the entity's in-flight Redis lock (no double
    # spend). Checked only when a lock reader is wired (skipped in pure-unit contexts).
    requires_in_flight_lock: bool = True
    # Enumeration (Option C): the per-scope sanctioned discovery tiers — the enumeration analogue
    # of ``enforce_tier_in_plan`` (an enumeration has no field ``tier_plan`` to check). COMMITTEE
    # people-discovery is a deterministic / scrape / CRM spend (tiers 1-3 by nature): an LLM can
    # never *be* the source of a person (anti-fabrication; admission clamps a people source's
    # discovery provenance to ≤3), so tier 4 is excluded here. The tier-4 role-inference LLM is a
    # *field-fill* on an already-admitted contact (the FIELD path), not an enumeration spend, so it
    # is not governed by this set. A scope absent from the map is unsanctioned (fail closed).
    enumeration_allowed_tiers: dict[EnumerationScope, tuple[SourceTier, ...]] = {
        EnumerationScope.COMMITTEE: (SourceTier(1), SourceTier(2), SourceTier(3)),
    }


DEFAULT_PRE_SPEND_POLICY = PreSpendPolicy()


def parse_gate_spec(gate: str | None) -> GateSpec | None:
    """Parse the per-field ``gate_spec`` out of ``field_definition.gate``.

    Returns a :class:`GateSpec` when ``gate`` is a JSON object of known keys; ``None`` for an empty
    column or a legacy gate expression (``"tier>=1"`` / ``"committee-gated"``) — those impose no
    pre-spend override (lenient by design: the column is shared with other gate semantics)."""
    if not gate:
        return None
    try:
        parsed = json.loads(gate)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    try:
        return GateSpec.model_validate(parsed)
    except ValidationError:
        return None


def _requires_strong_key(policy: PreSpendPolicy, spec: GateSpec | None) -> bool:
    """Effective strong-key requirement: the global policy OR a per-field override demanding it."""
    if spec is not None and (spec.requires_strong_key or spec.requires_official_domain):
        return True
    return policy.requires_strong_key


def _has_strong_key(entity: AccountEntity | ContactEntity) -> bool:
    """Whether a resolved entity carries a strong identity key (the same-name-trap defence).

    Account: ``primary_domain`` (the official domain). Contact: a verified LinkedIn URL or email."""
    if isinstance(entity, AccountEntity):
        return entity.primary_domain is not None
    return entity.linkedin_url is not None or entity.verified_email is not None


def _build_target_lock(entity: AccountEntity | ContactEntity, field: FieldDef) -> TargetLock:
    """Construct the :class:`TargetLock` for a *resolved* entity + field (no I/O — pure)."""
    if isinstance(entity, AccountEntity):
        domain = entity.primary_domain
        site = f"Prefer `site:{domain}` sources. " if domain else ""
        anchor = f" (the organization at {domain})" if domain else ""
        instruction = (
            f"Research ONLY {entity.canonical_name}{anchor} for field `{field.field_key}`. "
            f"{site}Do NOT drift to similarly-named organizations; if a source is about a "
            "different company, discard it (the same-name trap)."
        )
        identifiers: dict[str, JsonValue] = {
            "canonical_name": entity.canonical_name,
            "primary_domain": domain,
            "hq_geo": entity.hq_geo,
            "aliases": list(entity.aliases),
            "registry_ids": dict(entity.registry_ids),
        }
        return TargetLock(
            entity_id=entity.id,
            no_drift_instruction=instruction,
            canonical_domain=domain,
            identifiers=identifiers,
        )

    # ContactEntity: lock to the specific person, never another who shares the name.
    name = entity.full_name or f"contact:{entity.id}"
    handle = f" (verified profile {entity.linkedin_url})" if entity.linkedin_url else ""
    instruction = (
        f"Research ONLY the specific person {name}{handle}, a contact under account "
        f"{entity.account_entity_id}, for field `{field.field_key}`. Do NOT attribute facts "
        "about a different person who shares this name (the same-name trap)."
    )
    contact_identifiers: dict[str, JsonValue] = {
        "full_name": entity.full_name,
        "linkedin_url": entity.linkedin_url,
        "has_verified_email": entity.verified_email is not None,
        "account_entity_id": str(entity.account_entity_id),
        "geo": entity.geo,
    }
    return TargetLock(
        entity_id=entity.id,
        no_drift_instruction=instruction,
        canonical_domain=None,
        identifiers=contact_identifiers,
    )


def assemble_target_lock(entity: AccountEntity | ContactEntity, field: FieldDef) -> TargetLock:
    """Public convenience: build the target-lock context for a resolved entity + field (M9.1).

    Mirrors :meth:`PreSpendGateImpl.assemble_target_lock` (the protocol method) for callers that
    already hold the resolved entity (e.g. M8.1 mode-M2 profiling) and want it without the gate."""
    return _build_target_lock(entity, field)


async def _covered_tiers(conn: AsyncConnection, tier_plan: Sequence[str]) -> set[int]:
    """The set of source tiers the field's ``tier_plan`` sanctions (the tiers of its registered
    sources). Empty when the plan is empty or none of its sources are in ``source_manifest``."""
    keys = list(tier_plan)
    if not keys:
        return set()
    stmt = text("SELECT DISTINCT tier FROM source_manifest WHERE source_key IN :keys").bindparams(
        bindparam("keys", expanding=True)
    )
    rows = await conn.execute(stmt, {"keys": keys})
    return {int(row[0]) for row in rows.all()}


async def _registered_source_tier(
    conn: AsyncConnection, source_key: str
) -> tuple[int, bool] | None:
    row = (
        await conn.execute(
            text("SELECT tier, active FROM source_manifest WHERE source_key = :source_key"),
            {"source_key": source_key},
        )
    ).first()
    return None if row is None else (int(row[0]), bool(row[1]))


async def _effective_plan_reasons(
    conn: AsyncConnection,
    request: PreSpendRequest,
) -> list[str]:
    """Validate or first-freeze the caller's plan against database-derived canonical authority."""

    plan = request.effective_source_plan
    if plan is None:
        return []
    spec = await get_icp_version(conn, plan.workspace_id, plan.icp_key, plan.icp_version)
    if spec is None:
        return ["effective source plan does not reference an existing pinned ICP version"]

    frozen = await load_effective_source_plan(
        conn,
        workspace_id=plan.workspace_id,
        icp_key=plan.icp_key,
        icp_version=plan.icp_version,
        field_key=str(plan.field_key),
    )
    if frozen is None:
        candidates = await resolve_allowed_set(
            conn,
            spec,
            str(plan.field_key),
            entity_scope=request.entity_type.value,
        )
        canonical = EffectiveFieldSourcePlan.compile(
            workspace_id=spec.workspace_id,
            icp_key=spec.icp_key,
            icp_version=spec.version,
            field_key=str(plan.field_key),
            sources=tuple(
                EffectiveSourceAuthorization(
                    source_key=source.source_key,
                    source_tier=SourceTier(source.tier),
                )
                for source in candidates
            ),
        )
        if canonical != plan:
            return [
                "presented effective source plan does not equal the database-derived canonical "
                f"plan {canonical.plan_sha256} for the pinned ICP field"
            ]
        try:
            frozen = await freeze_effective_source_plan(
                conn,
                canonical,
                source_profile_ref=spec.source_profile_ref,
            )
        except EffectiveSourcePlanConflict as exc:
            return [str(exc)]

    if frozen != plan:
        return [
            f"effective source plan {plan.plan_sha256} does not match frozen canonical plan "
            f"{frozen.plan_sha256} for the pinned ICP field"
        ]
    return []


async def _record_gate_decision(
    conn: AsyncConnection, request: PreSpendRequest, decision: PreSpendDecision
) -> None:
    """Append the audit row (one per ``check``). Append-only by use — no mutation path."""
    await conn.execute(
        text(
            """
            INSERT INTO gate_decision
                (run_id, entity_id, entity_type, request_kind, field_key, enumeration_scope,
                 source_tier, source_key, effective_plan_sha256, effective_source_plan,
                 decision, reasons)
            VALUES
                (:run_id, :entity_id, CAST(:entity_type AS entity_type),
                 CAST(:request_kind AS pre_spend_kind), :field_key,
                 CAST(:enumeration_scope AS enumeration_scope), :source_tier,
                 :source_key, :effective_plan_sha256, CAST(:effective_source_plan AS jsonb),
                 CAST(:decision AS pre_spend_verdict), CAST(:reasons AS jsonb))
            """
        ),
        {
            "run_id": str(request.run_id),
            "entity_id": str(request.entity_id),
            "entity_type": request.entity_type.value,
            "request_kind": request.kind.value,
            "field_key": str(request.field_key) if request.field_key is not None else None,
            "enumeration_scope": request.scope.value if request.scope is not None else None,
            "source_tier": int(request.source_tier),
            "source_key": request.source_key,
            "effective_plan_sha256": (
                request.effective_source_plan.plan_sha256
                if request.effective_source_plan is not None
                else None
            ),
            "effective_source_plan": (
                serialize_value_json(request.effective_source_plan.model_dump(mode="json"))
                if request.effective_source_plan is not None
                else None
            ),
            "decision": decision.verdict.value,
            "reasons": serialize_value_json(list(decision.reasons)),
        },
    )


class PreSpendGateImpl:
    """The M9.1 pre-spend gate (implements :class:`clue_core.verification.PreSpendGate`).

    Constructed with the gate :class:`PreSpendPolicy`, a connection factory (defaults to a committed
    transaction per check), and an optional in-flight lock reader (a Redis client). Injected at the
    ``api`` composition root; per-client/ICP policy is loaded via :func:`load_pre_spend_policy`."""

    def __init__(
        self,
        *,
        policy: PreSpendPolicy = DEFAULT_PRE_SPEND_POLICY,
        conn_factory: ConnFactory = transaction,
        lock_reader: _LockReader | None = None,
        record_decisions: bool = True,
        sink: MetricSink | None = None,
        lock_token_for_run: Callable[[RunId], str] = run_lock_token,
    ) -> None:
        self._policy = policy
        self._conn_factory = conn_factory
        self._lock_reader = lock_reader
        self._record = record_decisions
        self._sink = sink
        self._lock_token_for_run = lock_token_for_run

    async def check(self, request: PreSpendRequest) -> PreSpendDecision:
        attrs: dict[str, object] = {
            ATTR_ENTITY_ID: str(request.entity_id),
            ATTR_ENTITY_TYPE: request.entity_type.value,
            ATTR_FIELD_KEY: str(request.field_key) if request.field_key is not None else "",
            ATTR_SOURCE_TIER: int(request.source_tier),
            ATTR_RUN_ID: str(request.run_id),
        }
        with traced_step(SPAN_VERIFICATION_PRE_SPEND_GATE, **attrs) as span:
            async with self._conn_factory() as conn:
                reasons = await self._collect_reasons(conn, request)
                verdict = PreSpendVerdict.REJECT if reasons else PreSpendVerdict.PASS
                decision = PreSpendDecision(verdict=verdict, reasons=tuple(reasons))
                if self._record:
                    await _record_gate_decision(conn, request, decision)
            apply_attributes(span, {ATTR_GATE_DECISION: verdict.value})
            self._emit_metric(request, verdict)
            return decision

    def with_conn_factory(self, conn_factory: ConnFactory) -> PreSpendGateImpl:
        """Clone this gate onto a caller-owned transaction.

        Committee materialisation admits a contact and role-gates it before the short committee
        transaction commits.  A gate opening its own transaction cannot see that new identity and
        would reject every legitimate role-inference call.  Rebinding preserves the exact policy,
        lock reader, audit, metric, and fencing-token behavior while making identity/schema reads
        and the decision receipt part of the caller's atomic transaction.
        """
        return PreSpendGateImpl(
            policy=self._policy,
            conn_factory=conn_factory,
            lock_reader=self._lock_reader,
            record_decisions=self._record,
            sink=self._sink,
            lock_token_for_run=self._lock_token_for_run,
        )

    async def assemble_target_lock(
        self, entity: AccountEntity | ContactEntity, field: FieldDef
    ) -> TargetLock:
        return _build_target_lock(entity, field)

    async def _collect_reasons(self, conn: AsyncConnection, request: PreSpendRequest) -> list[str]:
        reasons: list[str] = []
        # --- schema / scope gate (kind-specific) ---
        if request.kind is PreSpendKind.ENUMERATION:
            # No field → the per-field gate_spec (strong-key override) does not apply; fall back to
            # the global policy's strong-key requirement.
            gate_spec: GateSpec | None = None
            reasons.extend(self._enumeration_reasons(request))
        else:  # FIELD (the validator guarantees field_key is set)
            assert request.field_key is not None
            field_def = await get_field(conn, str(request.field_key))
            gate_spec = parse_gate_spec(field_def.gate) if field_def is not None else None
            reasons.extend(await self._field_reasons(conn, request, field_def))

        # Exact registry identity is common to both field fills and field-less enumerations. A
        # source tier is a trust classification, not permission for any provider at that tier.
        reasons.extend(await self._source_reasons(conn, request))

        # --- identity gate (keys on a resolved entity_id, never a free-text name) — BOTH kinds ---
        reasons.extend(await self._identity_reasons(conn, request, gate_spec))

        # --- in-flight lock (anti-double-spend; cost guard) — BOTH kinds ---
        reasons.extend(await self._lock_reasons(request))
        return reasons

    async def _field_reasons(
        self, conn: AsyncConnection, request: PreSpendRequest, field_def: FieldDef | None
    ) -> list[str]:
        """The FIELD schema gate: field registered, requested tier sanctioned by the field's
        ``tier_plan``, and (when a value is in hand) it passes the field's value schema."""
        reasons: list[str] = []
        if field_def is None:
            reasons.append(
                f"field_key {request.field_key!r} is not registered in the field registry"
            )
            return reasons
        if request.effective_source_plan is not None:
            # A supplied dynamic plan is execution authority, not the legacy tier-plan policy
            # approximation. It is therefore always validated exactly; disabling the legacy
            # ``enforce_tier_in_plan`` knob cannot turn a caller-created digest into authority.
            plan = request.effective_source_plan
            reasons.extend(await _effective_plan_reasons(conn, request))
            assert request.source_key is not None  # model validator
            authorization = plan.authorization_for(request.source_key)
            if authorization is None:
                reasons.append(
                    f"source_key {request.source_key!r} is not in effective plan "
                    f"{plan.plan_sha256} for field {request.field_key!r}"
                )
            elif int(authorization.source_tier) != int(request.source_tier):
                reasons.append(
                    f"source_key {request.source_key!r} is tier "
                    f"{authorization.source_tier} in effective plan {plan.plan_sha256}, not "
                    f"requested tier {request.source_tier}"
                )
        elif self._policy.enforce_tier_in_plan and field_def.tier_plan:
            if request.source_key is not None:
                if request.source_key not in field_def.tier_plan:
                    reasons.append(
                        f"source_key {request.source_key!r} is not in field "
                        f"{request.field_key!r}'s tier_plan {list(field_def.tier_plan)!r}"
                    )
            else:
                covered = await _covered_tiers(conn, field_def.tier_plan)
                if covered and int(request.source_tier) not in covered:
                    reasons.append(
                        f"source_tier {request.source_tier} is not in field "
                        f"{request.field_key!r}'s tier_plan (sanctioned tiers: "
                        f"{sorted(covered)})"
                    )
        if request.value_json is not None:
            try:
                await validate_value(conn, str(request.field_key), request.value_json)
            except (UnknownFieldError, ValueSchemaError) as exc:
                reasons.append(f"value_json fails the field's schema: {exc}")
        return reasons

    async def _source_reasons(self, conn: AsyncConnection, request: PreSpendRequest) -> list[str]:
        if request.source_key is None:
            return []
        registered = await _registered_source_tier(conn, request.source_key)
        if registered is None:
            return [f"source_key {request.source_key!r} is not registered"]
        registered_tier, active = registered
        reasons: list[str] = []
        if not active:
            reasons.append(f"source_key {request.source_key!r} is inactive")
        if registered_tier != int(request.source_tier):
            reasons.append(
                f"source_key {request.source_key!r} is registered at tier "
                f"{registered_tier}, not requested tier {request.source_tier}"
            )
        return reasons

    def _enumeration_reasons(self, request: PreSpendRequest) -> list[str]:
        """The ENUMERATION scope gate (Option C): the requested ``source_tier`` must be sanctioned
        by the policy for this enumeration ``scope`` — the field-less analogue of tier-in-plan. A
        scope with no configured tiers is unsanctioned (fail closed). Pure (no I/O)."""
        assert request.scope is not None  # guaranteed by PreSpendRequest._check_kind
        allowed = self._policy.enumeration_allowed_tiers.get(request.scope)
        if allowed is None:
            return [
                f"enumeration scope {request.scope.value!r} is not sanctioned by policy "
                "(no allowed tiers configured) — failing closed"
            ]
        if int(request.source_tier) not in {int(t) for t in allowed}:
            return [
                f"source_tier {request.source_tier} is not allowed for enumeration scope "
                f"{request.scope.value!r} (allowed: {sorted(int(t) for t in allowed)})"
            ]
        return []

    async def _identity_reasons(
        self, conn: AsyncConnection, request: PreSpendRequest, gate_spec: GateSpec | None
    ) -> list[str]:
        reasons: list[str] = []
        entity = await get_entity(conn, request.entity_id, request.entity_type)
        if entity is None:
            reasons.append(
                "entity_id does not resolve to a registered entity (failed the dedup-registry / "
                "existence gate — it may be a raw discovery hypothesis or a free-text name)"
            )
            return reasons
        if entity.status is AccountStatus.MERGED:
            reasons.append(
                f"entity {request.entity_id} is merged (redirect to merged_into "
                f"{entity.merged_into}); a merged entity is never spent on"
            )
        elif entity.status not in self._policy.allowed_statuses:
            allowed = ", ".join(s.value for s in self._policy.allowed_statuses)
            reasons.append(
                f"entity status {entity.status.value!r} is not in the allowed set ({allowed})"
            )
        if _requires_strong_key(self._policy, gate_spec) and not _has_strong_key(entity):
            reasons.append(
                "entity lacks a strong key (account primary_domain / contact LinkedIn URL or "
                "verified email) — refusing spend on a weakly-keyed entity (the same-name trap)"
            )
        if (
            request.effective_source_plan is not None
            and getattr(entity, "workspace_id", None) != request.effective_source_plan.workspace_id
        ):
            reasons.append(
                "effective source plan workspace does not match the resolved entity workspace"
            )
        return reasons

    async def _lock_reasons(self, request: PreSpendRequest) -> list[str]:
        if not (self._policy.requires_in_flight_lock and self._lock_reader is not None):
            return []
        key = lock_key(request.entity_type, request.entity_id)
        holder = await self._lock_reader.get(key)
        if holder is None:
            return []
        holder_token = holder.decode() if isinstance(holder, bytes) else str(holder)
        if holder_token != self._lock_token_for_run(request.run_id):
            return [
                "the entity's in-flight lock is held by a different run "
                "(anti-double-spend — another worker owns it)"
            ]
        return []

    def _emit_metric(self, request: PreSpendRequest, verdict: PreSpendVerdict) -> None:
        sink = self._sink or get_metric_sink()
        labels = {"entity_type": request.entity_type.value, "source_tier": str(request.source_tier)}
        sink.add(METRIC_PRESPEND_DECISIONS, 1, labels)
        if verdict is PreSpendVerdict.REJECT:
            sink.add(METRIC_PRESPEND_BLOCKED, 1, labels)


async def load_pre_spend_policy(
    conn: AsyncConnection,
    *,
    workspace_id: str | None = None,
    icp_version: int | None = None,
) -> PreSpendPolicy:
    """Load the most-specific :class:`PreSpendPolicy` for a scope: per-ICP → per-client → global
    default row → :data:`DEFAULT_PRE_SPEND_POLICY`. The latest ``version`` within the matched scope
    wins, with a deterministic ``created_at``/``policy_id`` tie-break (so a duplicate same-version
    row can never resolve non-deterministically — mirrors the M9.3 ``load_judge_policy`` precedent;
    the
    ``NULLS NOT DISTINCT`` slot uniqueness the B4-slice-1 migration adds prevents the duplicate for
    the global default row, and the tie-break covers any pre-existing/racing duplicate). Returns the
    built-in default when no row matches (policy-as-data; fail-soft)."""
    candidates: list[tuple[str | None, int | None]] = []
    if workspace_id is not None and icp_version is not None:
        candidates.append((workspace_id, icp_version))
    if workspace_id is not None:
        candidates.append((workspace_id, None))
    candidates.append((None, None))  # the global default row

    for scope_client, scope_icp in candidates:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT rules_json FROM pre_spend_policy
                    WHERE workspace_id IS NOT DISTINCT FROM :workspace_id
                      AND icp_version IS NOT DISTINCT FROM :icp_version
                    ORDER BY version DESC, created_at DESC, policy_id DESC
                    LIMIT 1
                    """
                ),
                {"workspace_id": scope_client, "icp_version": scope_icp},
            )
        ).first()
        if row is not None:
            rules = row[0]
            if isinstance(rules, str):
                rules = json.loads(rules)
            return PreSpendPolicy.model_validate(rules)
    return DEFAULT_PRE_SPEND_POLICY
