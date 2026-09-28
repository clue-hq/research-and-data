"""C7.2 immutable claim-support storage and live dependency resolution.

``DerivationStore`` owns normalized support edges inside the claim substrate. It validates the
complete ordered set before inserting it, locks support claims deterministically, and returns only
claim references. ``DerivationDependencyResolver`` re-resolves those references under current
tenancy, retention, verification, freshness, conflict, supersession, and erasure state; a derived
claim never stays eligible merely because it was valid when first judged.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    ClaimFlavor,
    ClaimId,
    EntityId,
    EntityType,
    FreshnessState,
    IdentityBinding,
    OperationId,
    ResearchSubjectRef,
    ResearchSupportRef,
    ResearchSupportRole,
    VerificationStatus,
    canonical_json,
    reference_time,
)
from clue_research.claimstore.claims import claims_by_ids, insert_claim
from clue_research.claimstore.merge import current_values
from clue_research.claimstore.tenancy import ALL_WORKSPACES, WorkspaceScope


class DerivationValidationError(ValueError):
    """A proposed support set failed a structural or live-eligibility gate."""


class DerivationDependencyState(StrEnum):
    """Current disposition of a claim used as a derivation dependency."""

    ELIGIBLE_FRESH = "eligible_fresh"
    STALE_RECHECK_REQUIRED = "stale_recheck_required"
    REVIEW_REQUIRED = "review_required"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"
    REDACTED = "redacted"
    RESTRICTED = "restricted"


class DerivationSetRef(BaseModel):
    """Reference-only immutable support-set result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    derived_claim_id: ClaimId
    operation_id: OperationId
    support_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supports: tuple[ResearchSupportRef, ...]


class DerivationDependencyResolution(BaseModel):
    """Bounded live resolution result; it contains references and states, never copied bodies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    state: DerivationDependencyState
    freshness: FreshnessState | None = None
    reason_codes: tuple[str, ...] = ()
    support_claim_ids: tuple[ClaimId, ...] = ()
    # Exact required transitive closure, excluding the root. Governance uses this to apply display
    # and outreach policy to every required dependency, preventing derived-claim laundering.
    required_transitive_claim_ids: tuple[ClaimId, ...] = ()
    traversed_nodes: int = Field(ge=0)
    max_depth_reached: int = Field(ge=0)


_STATE_PRECEDENCE: dict[DerivationDependencyState, int] = {
    DerivationDependencyState.ELIGIBLE_FRESH: 0,
    DerivationDependencyState.STALE_RECHECK_REQUIRED: 1,
    DerivationDependencyState.REVIEW_REQUIRED: 2,
    DerivationDependencyState.UNAVAILABLE: 3,
    DerivationDependencyState.REJECTED: 4,
    DerivationDependencyState.RESTRICTED: 5,
    DerivationDependencyState.REDACTED: 6,
}


def support_set_sha256(supports: Sequence[ResearchSupportRef]) -> str:
    """Stable hash of the exact ordered support identity/role/required tuple."""
    payload = [
        {
            "claim_id": str(support.claim_id),
            "role": support.role.value,
            "ordinal": support.ordinal,
            "required": support.required,
        }
        for support in supports
    ]
    return hashlib.sha256(canonical_json(cast(JsonValue, payload)).encode()).hexdigest()


def _validate_support_shape(
    supports: Sequence[ResearchSupportRef],
) -> tuple[ResearchSupportRef, ...]:
    ordered = tuple(supports)
    if not ordered:
        raise DerivationValidationError("a derived claim requires at least one support")
    if not any(support.required for support in ordered):
        raise DerivationValidationError("a derived claim requires at least one required support")
    if tuple(support.ordinal for support in ordered) != tuple(range(len(ordered))):
        raise DerivationValidationError("support ordinals must be contiguous from zero")
    edge_keys = tuple((support.claim_id, support.role) for support in ordered)
    if len(edge_keys) != len(set(edge_keys)):
        raise DerivationValidationError("duplicate supporting claim/role edge")
    return ordered


async def _contact_parent(conn: AsyncConnection, contact_id: EntityId) -> EntityId | None:
    return (
        await conn.execute(
            text("SELECT account_entity_id FROM contact_entity WHERE id = :contact_id"),
            {"contact_id": contact_id},
        )
    ).scalar_one_or_none()


async def _validate_relation(
    conn: AsyncConnection,
    *,
    derived: Claim,
    support: Claim,
    role: ResearchSupportRole,
) -> None:
    if support.entity_type is EntityType.CONTACT:
        is_weak = support.identity_binding is IdentityBinding.WEAK
        is_facet = str(support.field_key) == "contact.facet" or str(support.field_key).startswith(
            "contact.facet."
        )
        if is_weak or (is_facet and support.identity_binding is not IdentityBinding.STRONG):
            raise DerivationValidationError("contact support must be strongly identity-bound")

    if role is ResearchSupportRole.CLIENT_CAPABILITY:
        if (
            derived.product_id is None
            or support.product_id is None
            or support.product_id != derived.product_id
        ):
            raise DerivationValidationError(
                "client_capability requires support in the exact derived product scope"
            )
        return

    if derived.entity_id == support.entity_id:
        if role is ResearchSupportRole.EMPLOYER_CONTEXT:
            raise DerivationValidationError(
                "employer_context requires the contact's parent-account claim"
            )
        return

    if (
        derived.entity_type is EntityType.CONTACT
        and support.entity_type is EntityType.ACCOUNT
        and role in {ResearchSupportRole.EMPLOYER_CONTEXT, ResearchSupportRole.ACCOUNT_SIGNAL}
    ):
        parent = await _contact_parent(conn, derived.entity_id)
        if parent != support.entity_id:
            raise DerivationValidationError(
                "account support is not the derived contact's resolved employer"
            )
        return

    if (
        derived.entity_type is EntityType.ACCOUNT
        and support.entity_type is EntityType.CONTACT
        and role is ResearchSupportRole.ACCOUNT_SIGNAL
    ):
        parent = await _contact_parent(conn, support.entity_id)
        if parent != derived.entity_id:
            raise DerivationValidationError("contact signal is not bound to the derived account")
        return

    raise DerivationValidationError(
        f"support role {role.value} does not permit this cross-subject relation"
    )


async def _would_cycle(
    conn: AsyncConnection, derived_claim_id: ClaimId, supporting_claim_id: ClaimId
) -> bool:
    return bool(
        (
            await conn.execute(
                text(
                    """
                    WITH RECURSIVE dependencies(claim_id) AS (
                        SELECT CAST(:supporting_claim_id AS uuid)
                        UNION
                        SELECT edge.supporting_claim_id
                        FROM claim_derivation edge
                        JOIN dependencies prior ON edge.derived_claim_id = prior.claim_id
                    )
                    SELECT EXISTS (
                        SELECT 1 FROM dependencies
                        WHERE claim_id = CAST(:derived_claim_id AS uuid)
                    )
                    """
                ),
                {
                    "derived_claim_id": derived_claim_id,
                    "supporting_claim_id": supporting_claim_id,
                },
            )
        ).scalar_one()
    )


class DerivationDependencyResolver:
    """Bounded memoized live resolver with breadth-batched support and claim reads."""

    def __init__(self, *, max_depth: int = 8, max_nodes: int = 128) -> None:
        if max_depth < 1 or max_nodes < 1:
            raise ValueError("derivation resolver limits must be positive")
        self._max_depth = max_depth
        self._max_nodes = max_nodes

    async def resolve(
        self,
        conn: AsyncConnection,
        claim_id: ClaimId,
        *,
        scope: WorkspaceScope,
    ) -> DerivationDependencyResolution:
        graph = await self._load_graph(conn, claim_id, scope=scope)
        memo: dict[ClaimId, DerivationDependencyResolution] = {}
        visiting: set[ClaimId] = set()
        counter = [0]
        return self._resolve(
            claim_id,
            depth=0,
            graph=graph,
            memo=memo,
            visiting=visiting,
            counter=counter,
        )

    async def resolve_many(
        self,
        conn: AsyncConnection,
        claim_ids: Sequence[ClaimId],
        *,
        scope: WorkspaceScope,
    ) -> dict[ClaimId, DerivationDependencyResolution]:
        """Resolve several roots over one breadth-batched graph load."""

        roots = tuple(dict.fromkeys(claim_ids))
        if not roots:
            return {}
        graph = await self._load_graph_many(conn, roots, scope=scope)
        memo: dict[ClaimId, DerivationDependencyResolution] = {}
        results: dict[ClaimId, DerivationDependencyResolution] = {}
        for claim_id in roots:
            results[claim_id] = self._resolve(
                claim_id,
                depth=0,
                graph=graph,
                memo=memo,
                visiting=set(),
                counter=[0],
            )
        return results

    async def _load_graph(
        self,
        conn: AsyncConnection,
        root_claim_id: ClaimId,
        *,
        scope: WorkspaceScope,
    ) -> _DependencyGraph:
        """Load one bounded graph with one support query per depth, never per node."""

        return await self._load_graph_many(conn, (root_claim_id,), scope=scope)

    async def _load_graph_many(
        self,
        conn: AsyncConnection,
        root_claim_ids: Sequence[ClaimId],
        *,
        scope: WorkspaceScope,
    ) -> _DependencyGraph:
        """Load the union graph for several roots with one support query per breadth level."""

        seen: set[ClaimId] = set(root_claim_ids)
        frontier: tuple[ClaimId, ...] = tuple(root_claim_ids)
        supports: dict[ClaimId, tuple[ResearchSupportRef, ...]] = {}
        node_limited: set[ClaimId] = set()
        depth = 0
        while frontier:
            rows = await derivation_supports_batch(conn, frontier)
            for parent in frontier:
                supports[parent] = rows.get(parent, ())
            if depth >= self._max_depth:
                break
            next_frontier: list[ClaimId] = []
            for parent in frontier:
                for support in supports[parent]:
                    child = support.claim_id
                    if child in seen or child in node_limited:
                        continue
                    if len(seen) >= self._max_nodes:
                        node_limited.add(child)
                        continue
                    seen.add(child)
                    next_frontier.append(child)
            frontier = tuple(next_frontier)
            depth += 1

        ordered_ids = tuple(sorted(seen, key=str))
        visible = await claims_by_ids(conn, ordered_ids, scope=scope)
        # These remain separate histories: a recorded quality decision, never a writer's marker,
        # permits this profile's support. Ordinary reads already enforce its current assessment.
        quality_supported = frozenset(
            (
                await conn.execute(
                    text(
                        "SELECT claim_id FROM claim_quality_current WHERE claim_id=ANY(:ids) "
                        "AND conclusion='supported'"
                    ),
                    {"ids": list(visible)},
                )
            )
            .scalars()
            .all()
        )
        missing = tuple(claim_id for claim_id in ordered_ids if claim_id not in visible)
        scoped_audit = (
            await claims_by_ids(conn, missing, scope=scope, include_superseded=True)
            if missing
            else {}
        )
        operator_missing = tuple(claim_id for claim_id in missing if claim_id not in scoped_audit)
        operator_audit = (
            await claims_by_ids(
                conn,
                operator_missing,
                scope=ALL_WORKSPACES,
                include_superseded=True,
            )
            if operator_missing
            else {}
        )
        erased_reasons: dict[ClaimId, str] = {}
        if scoped_audit:
            erased_rows = (
                await conn.execute(
                    text(
                        "SELECT erased_claim_id, reason FROM dsar_tombstone "
                        "WHERE erased_claim_id IN :claim_ids"
                    ).bindparams(bindparam("claim_ids", expanding=True)),
                    {"claim_ids": list(scoped_audit)},
                )
            ).all()
            erased_reasons = {ClaimId(row[0]): str(row[1]) for row in erased_rows}

        field_keys = tuple(sorted({str(claim.field_key) for claim in visible.values()}))
        ttl_by_field: dict[str, timedelta | None] = {}
        if field_keys:
            meta_rows = (
                await conn.execute(
                    text(
                        "SELECT field_key, freshness_ttl FROM field_definition "
                        "WHERE field_key IN :field_keys"
                    ).bindparams(bindparam("field_keys", expanding=True)),
                    {"field_keys": list(field_keys)},
                )
            ).all()
            ttl_by_field = {str(row[0]): row[1] for row in meta_rows}

        field_claims = tuple(
            claim for claim in visible.values() if claim.claim_flavor is ClaimFlavor.FIELD_CLAIM
        )
        merged = (
            await current_values(
                conn,
                {claim.entity_id for claim in field_claims},
                {claim.field_key for claim in field_claims},
                scope=scope,
            )
            if field_claims
            else {}
        )
        conflicted = {
            (entity_id, field_key)
            for (entity_id, field_key), value in merged.items()
            if value.conflict
        }
        return _DependencyGraph(
            supports=supports,
            visible=visible,
            scoped_audit=frozenset(scoped_audit),
            operator_audit=frozenset(operator_audit),
            erased_reasons=erased_reasons,
            node_limited=frozenset(node_limited),
            ttl_by_field=ttl_by_field,
            conflicted=frozenset(conflicted),
            quality_supported=quality_supported,
        )

    def _resolve(
        self,
        claim_id: ClaimId,
        *,
        depth: int,
        graph: _DependencyGraph,
        memo: dict[ClaimId, DerivationDependencyResolution],
        visiting: set[ClaimId],
        counter: list[int],
    ) -> DerivationDependencyResolution:
        if claim_id in memo:
            return memo[claim_id]
        if claim_id in graph.node_limited:
            return DerivationDependencyResolution(
                claim_id=claim_id,
                state=DerivationDependencyState.UNAVAILABLE,
                reason_codes=("dependency_node_limit",),
                traversed_nodes=counter[0],
                max_depth_reached=depth,
            )
        if depth > self._max_depth:
            return DerivationDependencyResolution(
                claim_id=claim_id,
                state=DerivationDependencyState.UNAVAILABLE,
                reason_codes=("dependency_depth_limit",),
                traversed_nodes=counter[0],
                max_depth_reached=depth,
            )
        if counter[0] >= self._max_nodes:
            return DerivationDependencyResolution(
                claim_id=claim_id,
                state=DerivationDependencyState.UNAVAILABLE,
                reason_codes=("dependency_node_limit",),
                traversed_nodes=counter[0],
                max_depth_reached=depth,
            )
        if claim_id in visiting:
            return DerivationDependencyResolution(
                claim_id=claim_id,
                state=DerivationDependencyState.UNAVAILABLE,
                reason_codes=("dependency_cycle",),
                traversed_nodes=counter[0],
                max_depth_reached=depth,
            )

        counter[0] += 1
        claim = graph.visible.get(claim_id)
        if claim is None:
            resolution = self._missing_resolution(
                claim_id,
                graph=graph,
                depth=depth,
                counter=counter[0],
            )
            memo[claim_id] = resolution
            return resolution

        if claim.verification_status is VerificationStatus.REJECTED:
            resolution = DerivationDependencyResolution(
                claim_id=claim_id,
                state=DerivationDependencyState.REJECTED,
                reason_codes=("verification_rejected",),
                traversed_nodes=counter[0],
                max_depth_reached=depth,
            )
            memo[claim_id] = resolution
            return resolution
        if claim.id not in graph.quality_supported and claim.verification_status not in {
            VerificationStatus.VERIFIED,
            VerificationStatus.FLAGGED,
        }:
            resolution = DerivationDependencyResolution(
                claim_id=claim_id,
                state=DerivationDependencyState.UNAVAILABLE,
                reason_codes=("verification_incomplete",),
                traversed_nodes=counter[0],
                max_depth_reached=depth,
            )
            memo[claim_id] = resolution
            return resolution

        local_state, freshness, local_reasons = self._local_state(claim, graph=graph)
        if claim.verification_status is VerificationStatus.FLAGGED:
            local_state = max(
                (local_state, DerivationDependencyState.REVIEW_REQUIRED),
                key=_STATE_PRECEDENCE.__getitem__,
            )
            local_reasons = tuple(dict.fromkeys(("verification_flagged", *local_reasons)))
        if claim.claim_flavor is not ClaimFlavor.DERIVED:
            resolution = DerivationDependencyResolution(
                claim_id=claim_id,
                state=local_state,
                freshness=freshness,
                reason_codes=local_reasons,
                traversed_nodes=counter[0],
                max_depth_reached=depth,
            )
            memo[claim_id] = resolution
            return resolution

        supports = graph.supports.get(claim_id, ())
        if not supports:
            resolution = DerivationDependencyResolution(
                claim_id=claim_id,
                state=DerivationDependencyState.UNAVAILABLE,
                reason_codes=("support_set_missing",),
                traversed_nodes=counter[0],
                max_depth_reached=depth,
            )
            memo[claim_id] = resolution
            return resolution

        visiting.add(claim_id)
        required_results: list[DerivationDependencyResolution] = []
        try:
            for support in supports:
                child = self._resolve(
                    support.claim_id,
                    depth=depth + 1,
                    graph=graph,
                    memo=memo,
                    visiting=visiting,
                    counter=counter,
                )
                if support.required:
                    required_results.append(child)
        finally:
            visiting.remove(claim_id)

        states = [local_state, *(child.state for child in required_results)]
        state = max(states, key=_STATE_PRECEDENCE.__getitem__)
        reasons = list(local_reasons)
        for child in required_results:
            if child.state is not DerivationDependencyState.ELIGIBLE_FRESH:
                reasons.extend(
                    f"support_{child.claim_id}_{reason}" for reason in child.reason_codes
                )
        required_supports = tuple(support for support in supports if support.required)
        resolution = DerivationDependencyResolution(
            claim_id=claim_id,
            state=state,
            freshness=(
                FreshnessState.STALE
                if state is DerivationDependencyState.STALE_RECHECK_REQUIRED
                else freshness
            ),
            reason_codes=tuple(dict.fromkeys(reasons)),
            support_claim_ids=tuple(support.claim_id for support in supports),
            required_transitive_claim_ids=tuple(
                dict.fromkeys(
                    claim_id
                    for support, child in zip(required_supports, required_results, strict=True)
                    for claim_id in (
                        support.claim_id,
                        *child.required_transitive_claim_ids,
                    )
                )
            ),
            traversed_nodes=counter[0],
            max_depth_reached=max(
                [depth, *(child.max_depth_reached for child in required_results)]
            ),
        )
        memo[claim_id] = resolution
        return resolution

    @staticmethod
    def _missing_resolution(
        claim_id: ClaimId,
        *,
        graph: _DependencyGraph,
        depth: int,
        counter: int,
    ) -> DerivationDependencyResolution:
        if claim_id in graph.scoped_audit:
            reason = graph.erased_reasons.get(claim_id)
            erased = reason is not None
            reason_code = (
                {
                    "erasure": "erased_support",
                    "objection": "objection_erased_support",
                    "retention_expiry": "retention_expired_support",
                }.get(reason, "erased_support")
                if reason is not None
                else "erased_support"
            )
            return DerivationDependencyResolution(
                claim_id=claim_id,
                state=(
                    DerivationDependencyState.REDACTED
                    if erased
                    else DerivationDependencyState.UNAVAILABLE
                ),
                reason_codes=(reason_code,) if erased else ("superseded_or_expired",),
                traversed_nodes=counter,
                max_depth_reached=depth,
            )
        return DerivationDependencyResolution(
            claim_id=claim_id,
            state=(
                DerivationDependencyState.RESTRICTED
                if claim_id in graph.operator_audit
                else DerivationDependencyState.UNAVAILABLE
            ),
            reason_codes=(
                ("workspace_restricted",)
                if claim_id in graph.operator_audit
                else ("claim_missing",)
            ),
            traversed_nodes=counter,
            max_depth_reached=depth,
        )

    @staticmethod
    def _local_state(
        claim: Claim,
        *,
        graph: _DependencyGraph,
    ) -> tuple[DerivationDependencyState, FreshnessState, tuple[str, ...]]:
        ttl = graph.ttl_by_field.get(str(claim.field_key))
        freshness = (
            FreshnessState.STALE
            if ttl is not None and datetime.now(UTC) - reference_time(claim) > ttl
            else FreshnessState.FRESH
        )
        if (
            claim.claim_flavor is ClaimFlavor.FIELD_CLAIM
            and (claim.entity_id, str(claim.field_key)) in graph.conflicted
        ):
            return (
                DerivationDependencyState.REVIEW_REQUIRED,
                freshness,
                ("support_field_conflict",),
            )
        if freshness is FreshnessState.STALE:
            return (
                DerivationDependencyState.STALE_RECHECK_REQUIRED,
                freshness,
                ("support_stale",),
            )
        return DerivationDependencyState.ELIGIBLE_FRESH, freshness, ()


@dataclass(frozen=True)
class _DependencyGraph:
    quality_supported: frozenset[ClaimId]
    supports: dict[ClaimId, tuple[ResearchSupportRef, ...]]
    visible: dict[ClaimId, Claim]
    scoped_audit: frozenset[ClaimId]
    operator_audit: frozenset[ClaimId]
    erased_reasons: dict[ClaimId, str]
    node_limited: frozenset[ClaimId]
    ttl_by_field: dict[str, timedelta | None]
    conflicted: frozenset[tuple[EntityId, str]]


async def derivation_supports_batch(
    conn: AsyncConnection,
    derived_claim_ids: Sequence[ClaimId],
) -> dict[ClaimId, tuple[ResearchSupportRef, ...]]:
    """Load all support sets for one breadth level in one ordered query."""

    if not derived_claim_ids:
        return {}
    rows = (
        await conn.execute(
            text(
                """
                SELECT derived_claim_id, supporting_claim_id, support_role, ordinal,
                       support_required
                FROM claim_derivation
                WHERE derived_claim_id IN :derived_claim_ids
                ORDER BY derived_claim_id, ordinal
                """
            ).bindparams(bindparam("derived_claim_ids", expanding=True)),
            {"derived_claim_ids": list(derived_claim_ids)},
        )
    ).all()
    grouped: dict[ClaimId, list[ResearchSupportRef]] = {
        ClaimId(value): [] for value in derived_claim_ids
    }
    for row in rows:
        grouped[ClaimId(row[0])].append(
            ResearchSupportRef(
                claim_id=ClaimId(row[1]),
                role=ResearchSupportRole(row[2]),
                ordinal=int(row[3]),
                required=bool(row[4]),
            )
        )
    return {claim_id: tuple(values) for claim_id, values in grouped.items()}


async def derivation_supports(
    conn: AsyncConnection, derived_claim_id: ClaimId
) -> tuple[ResearchSupportRef, ...]:
    """Ordered support references for one derived claim."""
    return (await derivation_supports_batch(conn, (derived_claim_id,))).get(derived_claim_id, ())


async def affected_derivations(
    conn: AsyncConnection, supporting_claim_ids: Sequence[ClaimId]
) -> tuple[ClaimId, ...]:
    """All direct and transitive derived dependents of the supplied claims."""
    ids = tuple(str(claim_id) for claim_id in supporting_claim_ids)
    if not ids:
        return ()
    stmt = text(
        """
        WITH RECURSIVE affected(derived_claim_id) AS (
            SELECT DISTINCT derived_claim_id
            FROM claim_derivation
            WHERE supporting_claim_id IN :supporting_ids
            UNION
            SELECT edge.derived_claim_id
            FROM claim_derivation edge
            JOIN affected prior ON edge.supporting_claim_id = prior.derived_claim_id
        )
        SELECT derived_claim_id FROM affected ORDER BY derived_claim_id
        """
    ).bindparams(bindparam("supporting_ids", expanding=True))
    rows = (await conn.execute(stmt, {"supporting_ids": ids})).scalars().all()
    return tuple(ClaimId(row) for row in rows)


class DerivationStore:
    """Claimstore-owned transactional writer for one complete immutable support set."""

    def __init__(self, *, resolver: DerivationDependencyResolver | None = None) -> None:
        self._resolver = resolver or DerivationDependencyResolver()

    async def by_operation(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        operation_id: OperationId,
    ) -> DerivationSetRef | None:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT derived_claim_id
                    FROM claim_derivation
                    WHERE workspace_id = :workspace_id AND operation_id = :operation_id
                    ORDER BY ordinal
                    LIMIT 1
                    """
                ),
                {"workspace_id": workspace_id, "operation_id": operation_id},
            )
        ).first()
        if row is None:
            return None
        derived_id = ClaimId(row[0])
        supports = await derivation_supports(conn, derived_id)
        return DerivationSetRef(
            workspace_id=workspace_id,
            derived_claim_id=derived_id,
            operation_id=operation_id,
            support_set_sha256=support_set_sha256(supports),
            supports=supports,
        )

    async def validate(
        self,
        conn: AsyncConnection,
        derived_claim: Claim,
        target: ResearchSubjectRef,
        supports: Sequence[ResearchSupportRef],
        *,
        workspace_id: str,
        scope: WorkspaceScope,
    ) -> DerivationSetRef:
        ordered = _validate_support_shape(supports)
        if derived_claim.claim_flavor is not ClaimFlavor.DERIVED:
            raise DerivationValidationError("derived claim must have claim_flavor=derived")
        if (
            derived_claim.entity_id != target.entity_id
            or derived_claim.entity_type is not target.entity_type
        ):
            raise DerivationValidationError("derived claim does not match the exact target")
        if any(support.claim_id == derived_claim.id for support in ordered):
            raise DerivationValidationError("a derived claim cannot support itself")
        if (
            derived_claim.reuse_scope.value == "tenant_private"
            and derived_claim.workspace_id != workspace_id
        ):
            raise DerivationValidationError("derived claim workspace mismatch")

        support_map = await claims_by_ids(
            conn, (support.claim_id for support in ordered), scope=scope
        )
        missing = [support.claim_id for support in ordered if support.claim_id not in support_map]
        if missing:
            raise DerivationValidationError(
                "support claims are missing, superseded, expired, erased, or out of scope: "
                f"{missing}"
            )

        for support_ref in ordered:
            support = support_map[support_ref.claim_id]
            if (
                support.reuse_scope.value == "tenant_private"
                and support.workspace_id != workspace_id
            ):
                raise DerivationValidationError("supporting claim workspace mismatch")
            if (
                support.reuse_scope.value == "tenant_private"
                and derived_claim.reuse_scope.value != "tenant_private"
            ):
                raise DerivationValidationError(
                    "a public derivation cannot depend on tenant-private support"
                )
            if support.product_id is not None and support.product_id != derived_claim.product_id:
                raise DerivationValidationError("supporting claim product mismatch")
            await _validate_relation(
                conn, derived=derived_claim, support=support, role=support_ref.role
            )
            if await _would_cycle(conn, derived_claim.id, support.id):
                raise DerivationValidationError("claim derivation cycle detected")
            resolution = await self._resolver.resolve(conn, support.id, scope=scope)
            if (
                support_ref.required
                and resolution.state is not DerivationDependencyState.ELIGIBLE_FRESH
            ):
                raise DerivationValidationError(
                    f"required support {support.id} is not eligible: {resolution.state.value}"
                )

        return DerivationSetRef(
            workspace_id=workspace_id,
            derived_claim_id=derived_claim.id,
            operation_id=OperationId(UUID(int=0)),
            support_set_sha256=support_set_sha256(ordered),
            supports=ordered,
        )

    async def create(
        self,
        conn: AsyncConnection,
        derived_claim: Claim,
        target: ResearchSubjectRef,
        supports: Sequence[ResearchSupportRef],
        *,
        workspace_id: str,
        operation_id: OperationId,
        scope: WorkspaceScope,
    ) -> DerivationSetRef:
        existing = await self.by_operation(
            conn, workspace_id=workspace_id, operation_id=operation_id
        )
        if existing is not None:
            return existing

        ordered = _validate_support_shape(supports)
        support_ids = sorted({str(support.claim_id) for support in ordered})
        lock_stmt = text("SELECT id FROM claim WHERE id IN :ids ORDER BY id FOR UPDATE").bindparams(
            bindparam("ids", expanding=True)
        )
        await conn.execute(lock_stmt, {"ids": support_ids})
        # A concurrent request may have committed while this transaction waited on the first
        # support row. Read again after the deterministic lock boundary so duplicate operations
        # resolve to the original complete set rather than racing into a duplicate claim insert.
        existing = await self.by_operation(
            conn, workspace_id=workspace_id, operation_id=operation_id
        )
        if existing is not None:
            return existing

        prepared = await self.validate(
            conn,
            derived_claim,
            target,
            ordered,
            workspace_id=workspace_id,
            scope=scope,
        )
        await insert_claim(conn, derived_claim)
        for support in ordered:
            await conn.execute(
                text(
                    """
                    INSERT INTO claim_derivation
                        (workspace_id, derived_claim_id, supporting_claim_id, support_role,
                         ordinal, support_required, operation_id)
                    VALUES
                        (:workspace_id, :derived_claim_id, :supporting_claim_id,
                         CAST(:support_role AS research_support_role), :ordinal,
                         :support_required, :operation_id)
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "derived_claim_id": derived_claim.id,
                    "supporting_claim_id": support.claim_id,
                    "support_role": support.role.value,
                    "ordinal": support.ordinal,
                    "support_required": support.required,
                    "operation_id": operation_id,
                },
            )
        return prepared.model_copy(update={"operation_id": operation_id})
