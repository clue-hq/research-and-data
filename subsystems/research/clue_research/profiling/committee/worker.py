"""Committee discovery — the M8.3 worker (mode M3).

``discover_committee`` is the contact-axis trunk: within a known explicitly selected account, it
enumerates candidate people via the bound :class:`CommitteeSource`s, then runs each through the M2
existence gate (:mod:`admission`) and writes their discovery-provenance + professional-fact claims,
producing the **buying committee** (Output 3) and the V1 contact graph (substrate §7). Whether it
*also* infers +
plausibility-gates each member's committee role (:mod:`roles`) is the caller's choice: the
``role_inference`` mode either keeps that judgment here (``worker_llm``) or defers it to the account
agent (``agent_deferred``), which is discovery/identity only. It is a bounded ``expand`` over one
company's people: it stops on a marginal-yield drop or the committee budget cap (:mod:`stopping`),
and reports committee coverage confidence (:mod:`coverage`) rather than implying exhaustiveness.

It returns **references** (contact ids + claim ids), never blobs. :class:`CommitteeAspectWorker`
adapts it to the M7 ``AspectWorker`` seam (the orchestrator hands it an ``AspectContext`` and never
a connection, so the worker opens one from an injected ``ConnFactory`` — the M6 pattern).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Literal

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AspectContext,
    ClaimId,
    ClaimProvenanceKind,
    CostCents,
    EntityId,
    EntityType,
    EnumerationScope,
    ExtractionMethod,
    ICPSpec,
    IdentityBinding,
    LLMGateway,
    Persona,
    PreSpendGate,
    PreSpendKind,
    PreSpendRequest,
    PreSpendVerdict,
    ResearchMode,
    RunId,
    SourceTier,
    UseClass,
    WorkerResult,
    WorkerStatus,
    canonical_json,
    contact_claim,
    revalidate_with,
)
from clue_db import ConnFactory
from clue_research.claimstore import WorkspaceScope, claims_for, insert_claim
from clue_research.icp.spec import get_icp_version
from clue_research.identity import get_account, stamp_reuse, surviving_id
from clue_research.profiling.committee.admission import AdmissionStatus, admit_candidate
from clue_research.profiling.committee.coverage import estimate_committee_coverage
from clue_research.profiling.committee.fields import PERSONA, ROLE_ON_COMMITTEE
from clue_research.profiling.committee.results import (
    DEFAULT_COMMITTEE_CONFIG,
    CommitteeConfig,
    CommitteeMemberRef,
    CommitteeResult,
)
from clue_research.profiling.committee.roles import (
    RoleInference,
    RoleVerdict,
    gate_role,
    infer_role,
)
from clue_research.profiling.committee.sources import (
    CandidateProfessionalFact,
    CommitteePersonCandidate,
    CommitteeSource,
    order_committee_sources,
)
from clue_research.profiling.committee.stopping import CommitteeStoppingRule, CommitteeStopReason

# Default personas to consider when the ICP does not narrow them (D5: read per ICP version).
_ALL_PERSONAS: tuple[Persona, ...] = tuple(Persona)

# Who judges the committee role (contract §5.2 steps 1-2 — discovery/identity is not role judgment):
#   ``worker_llm``      — this worker infers + plausibility-gates the role inline (legacy default).
#   ``agent_deferred``  — discovery/identity only: zero role work, zero gateway calls; the account
#                         agent judges roles afterwards and writes them back through its own tool.
RoleInferenceMode = Literal["worker_llm", "agent_deferred"]


class ProfessionalFactReplayConflict(RuntimeError):
    """The same immutable snapshot identity attempted to write a different professional fact."""


def _strong_key(candidate: CommitteePersonCandidate) -> str | None:
    """The normalized in-stream dedup key for a candidate (its strong key), or ``None``.

    Matches the M2 deterministic contact normalization (lowercased, trailing-slash-stripped) so the
    worker's in-stream dedup agrees with the identity service's authoritative dedup."""
    for raw in (candidate.linkedin_url, candidate.verified_email):
        if raw and raw.strip():
            return raw.strip().rstrip("/").lower()
    return None


def _provenance_params(
    candidate: CommitteePersonCandidate,
) -> tuple[ExtractionMethod, SourceTier, str, str] | None:
    """The provenance flavor for a role/persona claim derived from the LLM role inference, or
    ``None`` when the candidate cannot ground one.

    The role is an LLM judgment — the least-trusted layer (tier 4), grounded in the person's title
    (the ``evidence_span``) found at a public URL (substrate §4). The tier-4 path requires BOTH a
    grounding URL *and* a non-empty title: the frozen ``core.Claim`` validator requires a
    ``source_url`` for any ``llm_synthesis`` claim, and a tier-4 claim with a null
    ``evidence_span`` can never be promoted (``core.can_be_promoted``).

    When either is missing this returns ``None`` and the caller writes **no** role/persona claim.
    M6.3's ``HUMAN``/tier-1 derived-claim convention is **retired here** (contract §5.2: "must not
    create new false human provenance; agent-derived role writes must remain identified as
    agent-derived") — stamping an LLM guess as a human-asserted fact is the defect, not the fix.
    An ungrounded candidate keeps an honestly empty role; the member itself still survives via its
    discovery-provenance and professional-fact claims."""
    grounding_url = candidate.source_url or candidate.linkedin_url
    if grounding_url is not None and candidate.title and candidate.title.strip():
        return (
            ExtractionMethod.LLM_SYNTHESIS,
            SourceTier(4),
            grounding_url,
            f"title: {candidate.title}",
        )
    return None


async def write_committee_claim(
    conn: AsyncConnection,
    contact_entity_id: EntityId,
    field_key: str,
    value_json: JsonValue,
    *,
    confidence: float,
    method: ExtractionMethod,
    tier: SourceTier,
    source_url: str | None,
    evidence_span: str | None,
    run_id: RunId,
    workspace_id: str,
    identity_binding: IdentityBinding,
    product_id: str | None,
) -> ClaimId:
    """Write (idempotently) one tenant-private committee field claim for a contact.

    Idempotent on ``(contact, field, run)`` — a replay reuses the existing claim. Every committee
    field claim is ``use_class=professional-public`` (role/persona are professional-public by
    construction; M8.4 computes per-claim use-class for personal facets) and stamped tenant-private
    (a client's committee assessment never amortizes across clients)."""
    scope = WorkspaceScope.for_workspace(workspace_id)
    for existing in await claims_for(conn, contact_entity_id, field_key, scope=scope):
        if existing.run_id == run_id:
            return existing.id

    claim = contact_claim(
        entity_id=contact_entity_id,
        field_key=field_key,
        value_json=value_json,
        source_tier=tier,
        extraction_method=method,
        confidence=confidence,
        run_id=run_id,
        research_mode=ResearchMode.COMMITTEE_DISCOVERY,
        provenance_kind=ClaimProvenanceKind.PLATFORM_INFERRED,
        identity_binding=identity_binding,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
        source_url=source_url,
        evidence_span=evidence_span,
    )
    claim = revalidate_with(
        stamp_reuse(claim, workspace_id=workspace_id),
        product_id=product_id,
    )
    return await insert_claim(conn, claim)


async def _write_role_and_persona(
    conn: AsyncConnection,
    contact_entity_id: EntityId,
    candidate: CommitteePersonCandidate,
    verdict: RoleVerdict,
    *,
    run_id: RunId,
    workspace_id: str,
    identity_binding: IdentityBinding,
    product_id: str | None,
) -> tuple[ClaimId, ClaimId] | None:
    """Write the ``contact.role_on_committee`` (with the plausibility verdict) + ``contact.persona``
    claims for one admitted member; returns their claim ids.

    Returns ``None`` — writing **neither** claim — when the candidate cannot ground a tier-4
    agent-derived role (:func:`_provenance_params`). The pair is written together or not at all:
    never a half-written role without its persona, and never a fallback provenance."""
    provenance = _provenance_params(candidate)
    if provenance is None:
        return None
    method, tier, source_url, evidence_span = provenance
    role_claim_id = await write_committee_claim(
        conn,
        contact_entity_id,
        ROLE_ON_COMMITTEE,
        {
            "role": verdict.role.value,
            "confidence": verdict.confidence,
            "plausible": verdict.plausible,
            "rationale": verdict.rationale,
        },
        confidence=verdict.confidence,
        method=method,
        tier=tier,
        source_url=source_url,
        evidence_span=evidence_span,
        run_id=run_id,
        workspace_id=workspace_id,
        identity_binding=identity_binding,
        product_id=product_id,
    )
    persona_claim_id = await write_committee_claim(
        conn,
        contact_entity_id,
        PERSONA,
        verdict.role.value,
        confidence=verdict.confidence,
        method=method,
        tier=tier,
        source_url=source_url,
        evidence_span=evidence_span,
        run_id=run_id,
        workspace_id=workspace_id,
        identity_binding=identity_binding,
        product_id=product_id,
    )
    return role_claim_id, persona_claim_id


async def _write_professional_fact(
    conn: AsyncConnection,
    contact_entity_id: EntityId,
    fact: CandidateProfessionalFact,
    *,
    run_id: RunId,
    workspace_id: str,
    identity_binding: IdentityBinding,
    product_id: str | None,
) -> ClaimId:
    """Materialize one snapshot fact exactly once after strong identity admission."""

    if identity_binding is not IdentityBinding.STRONG:
        raise ValueError("professional contact facts require strong contact/account admission")
    scope = WorkspaceScope.for_workspace(workspace_id)
    for existing in await claims_for(conn, contact_entity_id, fact.field_key, scope=scope):
        if (
            existing.run_id != run_id
            or existing.source_key != fact.source_key
            or existing.product_id != product_id
        ):
            continue
        equivalent = (
            canonical_json(existing.value_json) == canonical_json(fact.value_json)
            and existing.source_tier == fact.source_tier
            and existing.source_url == fact.source_url
            and existing.evidence_span == fact.evidence_span
            and existing.artifact_key == fact.artifact_key
            and existing.source_operation_ref == fact.source_operation_ref
            and existing.source_snapshot_ref == fact.source_snapshot_ref
            and existing.source_request_ref == fact.source_request_ref
            and existing.provenance_kind is not None
            and existing.provenance_kind.value == fact.provenance_kind.value
            and existing.identity_binding is IdentityBinding.STRONG
            and existing.use_class is UseClass.PROFESSIONAL_PUBLIC
        )
        if not equivalent:
            raise ProfessionalFactReplayConflict(
                "immutable professional snapshot replay changed "
                f"{fact.field_key!r} for contact {contact_entity_id}"
            )
        return existing.id

    claim = contact_claim(
        entity_id=contact_entity_id,
        field_key=str(fact.field_key),
        value_json=fact.value_json,
        source_tier=fact.source_tier,
        extraction_method=ExtractionMethod.API,
        confidence=fact.confidence,
        run_id=run_id,
        research_mode=ResearchMode.COMMITTEE_DISCOVERY,
        provenance_kind=ClaimProvenanceKind(fact.provenance_kind.value),
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
        source_url=fact.source_url,
        evidence_span=fact.evidence_span,
        observed_at=fact.observed_at,
        cost_cents=Decimal(0),
    )
    claim = revalidate_with(
        stamp_reuse(claim, workspace_id=workspace_id),
        source_key=fact.source_key,
        artifact_key=fact.artifact_key,
        source_operation_ref=fact.source_operation_ref,
        source_snapshot_ref=fact.source_snapshot_ref,
        source_request_ref=fact.source_request_ref,
        product_id=product_id,
    )
    return await insert_claim(conn, claim)


async def _write_professional_facts(
    conn: AsyncConnection,
    contact_entity_id: EntityId,
    candidate: CommitteePersonCandidate,
    *,
    run_id: RunId,
    workspace_id: str,
    identity_binding: IdentityBinding,
    product_id: str | None,
) -> tuple[ClaimId, ...]:
    return tuple(
        [
            await _write_professional_fact(
                conn,
                contact_entity_id,
                fact,
                run_id=run_id,
                workspace_id=workspace_id,
                identity_binding=identity_binding,
                product_id=product_id,
            )
            for fact in candidate.professional_facts
        ]
    )


async def discover_committee(
    conn: AsyncConnection,
    *,
    account_entity_id: EntityId,
    run_id: RunId,
    workspace_id: str,
    sources: Sequence[CommitteeSource],
    gateway: LLMGateway,
    spec: ICPSpec | None = None,
    role_model: str | None = None,
    relevant_personas: tuple[Persona, ...] = _ALL_PERSONAS,
    source_plan: Sequence[str] | None = None,
    budget_cap_cents: CostCents | None = None,
    pre_spend_gate: PreSpendGate | None = None,
    config: CommitteeConfig = DEFAULT_COMMITTEE_CONFIG,
    role_inference: RoleInferenceMode = "worker_llm",
) -> CommitteeResult:
    """Discover the buying committee for one explicitly selected account (mode M3).

    Existence-gates every candidate through M2 (a strong-key-less candidate is dropped), writes
    discovery-provenance + professional-fact claims, and bounds the walk by marginal-yield / budget.
    ``workspace_id`` binds the tenant-private claims.

    ``role_inference`` decides who judges the committee role (:data:`RoleInferenceMode`):

    * ``worker_llm`` (default) — this worker infers + plausibility-gates each admitted member's role
      and writes the role/persona claim pair. A candidate that cannot ground an agent-derived role
      (:func:`_provenance_params`) skips the inference entirely — no gate check, no LLM call, no
      spend — and is admitted with an honestly empty role.
    * ``agent_deferred`` — discovery and identity only. **No role work at all**: no role pre-spend
      gate, no inference, no gateway call, no role/persona claim. Every admitted member is returned
      roleless, and the account agent judges the roles afterwards (contract §5.2 steps 1-2).

    ``role_model`` (or ``config.role_model``) is the gateway model id for role inference — required
    in ``worker_llm`` mode, fails loud (model as config, never hardcoded); irrelevant in
    ``agent_deferred`` mode, which never calls the gateway. When a ``pre_spend_gate`` is injected
    (M9.1), each people-source enumeration is gated as an ``ENUMERATION``/``COMMITTEE`` spend and
    each role-inference LLM call as a ``FIELD`` spend before it runs (REJECT skips that spend; the
    committee graph is otherwise preserved)."""
    infer_roles_here = role_inference == "worker_llm"
    model = role_model or config.role_model
    if infer_roles_here and not model:
        raise ValueError(
            "a role-inference model id is required (pass role_model=, or set config.role_model) — "
            "the model is config, never hardcoded (gateway seam)"
        )

    survivor_id = await surviving_id(conn, account_entity_id, EntityType.ACCOUNT)
    account = await get_account(conn, survivor_id)
    if account is None:
        raise ValueError(f"account {account_entity_id} not found — cannot discover its committee")

    ordered = order_committee_sources(sources, source_plan)
    all_channels = [source.source_key for source in ordered]
    rule = CommitteeStoppingRule(config.stopping, budget_cap_cents=budget_cap_cents)

    seen_keys: set[str] = set()
    seen_contact_ids: set[EntityId] = set()  # dedup on the *resolved* contact, not the strong key
    members: list[CommitteeMemberRef] = []
    admitted = dropped = candidates_seen_total = 0
    total_cost = Decimal(0)
    channels_searched: list[str] = []
    stop_reason = CommitteeStopReason.EXHAUSTED

    for source in ordered:
        channels_searched.append(source.source_key)
        # Pre-spend gate (M9.1 Option C): "find people AT this account" is an ENUMERATION spend (no
        # single field) — keyed on the account + COMMITTEE scope at the people-source tier. REJECT
        # skips this source before its external call.
        if pre_spend_gate is not None:
            decision = await pre_spend_gate.check(
                PreSpendRequest(
                    entity_id=account.id,
                    entity_type=EntityType.ACCOUNT,
                    kind=PreSpendKind.ENUMERATION,
                    scope=EnumerationScope.COMMITTEE,
                    source_tier=SourceTier(source.tier),
                    source_key=source.source_key,
                    run_id=run_id,
                )
            )
            if decision.verdict is PreSpendVerdict.REJECT:
                continue
        candidates = await source.find_candidates(account, limit=config.per_source_limit)
        new_admits = 0
        seen_this_source = 0
        source_cost = Decimal(0)

        for candidate in candidates:
            seen_this_source += 1
            candidates_seen_total += 1
            key = _strong_key(candidate)
            if key is not None and key in seen_keys:
                continue  # dedup across sources (the identity service is the authoritative dedup)

            outcome = await admit_candidate(
                conn, account, candidate, run_id=run_id, source_tier=source.tier
            )
            total_cost += outcome.cost_cents
            source_cost += outcome.cost_cents
            if outcome.status is AdmissionStatus.DROPPED:
                dropped += 1
                continue

            if key is not None:
                seen_keys.add(key)
            contact_entity_id = outcome.contact_entity_id
            assert contact_entity_id is not None  # ADMITTED always carries a contact id
            assert outcome.discovery_claim_id is not None

            # Two different strong keys (e.g. LinkedIn + verified email) can resolve to the SAME
            # contact (the M2 OR-match), which the strong-key dedup above misses. Dedup on the
            # resolved contact so a person is counted/role-inferred once (the new channel's
            # discovery-provenance was still recorded by admit_candidate above).
            if contact_entity_id in seen_contact_ids:
                continue
            seen_contact_ids.add(contact_entity_id)

            # Role judgment — skipped entirely in ``agent_deferred`` mode (the account agent owns
            # it), and skipped for a candidate that cannot ground an agent-derived role: without a
            # grounding URL and a title, ``_write_role_and_persona`` would refuse to write anything,
            # so inferring the role first would only burn a gate check and an LLM call to discard
            # the verdict. Either way the member is admitted with an honestly empty role.
            verdict: RoleVerdict | None = None
            role_ids: tuple[ClaimId, ClaimId] | None = None
            if infer_roles_here and _provenance_params(candidate) is not None:
                # Pre-spend gate (M9.1): role inference is a tier-4 LLM FIELD spend on the admitted
                # contact's ROLE_ON_COMMITTEE (empty tier_plan → no tier-in-plan reject). On REJECT
                # skip the LLM; gate_role falls back to the heuristic role, so the committee graph
                # survives.
                role_gate_rejected = False
                if pre_spend_gate is not None:
                    role_decision = await pre_spend_gate.check(
                        PreSpendRequest(
                            entity_id=contact_entity_id,
                            entity_type=EntityType.CONTACT,
                            field_key=ROLE_ON_COMMITTEE,
                            source_tier=SourceTier(4),
                            source_key="llm_role_inference",
                            run_id=run_id,
                        )
                    )
                    role_gate_rejected = role_decision.verdict is PreSpendVerdict.REJECT
                if role_gate_rejected:
                    inference = RoleInference(
                        role=None, confidence=0.0, rationale="role-inference gate-rejected"
                    )
                else:
                    assert model  # guarded above: worker_llm mode requires a role model
                    inference = infer_role(
                        gateway,
                        model,
                        candidate.title,
                        account,
                        relevant_personas=relevant_personas,
                    )
                verdict = gate_role(
                    inference,
                    candidate.title,
                    implausible_confidence_ceiling=config.implausible_confidence_ceiling,
                    fallback_confidence=config.fallback_confidence,
                )
                total_cost += verdict.cost_cents
                source_cost += verdict.cost_cents

                role_ids = await _write_role_and_persona(
                    conn,
                    contact_entity_id,
                    candidate,
                    verdict,
                    run_id=run_id,
                    workspace_id=workspace_id,
                    identity_binding=outcome.identity_binding,
                    product_id=spec.product_id if spec is not None else None,
                )
            professional_claim_ids = await _write_professional_facts(
                conn,
                contact_entity_id,
                candidate,
                run_id=run_id,
                workspace_id=workspace_id,
                identity_binding=outcome.identity_binding,
                product_id=spec.product_id if spec is not None else None,
            )
            admitted += 1
            new_admits += 1
            if verdict is None or role_ids is None:
                # No role inference for this member: either the run defers role judgment to the
                # account agent (``agent_deferred``), or the candidate could not ground an
                # agent-derived role (no URL and/or no title) so no role/persona claim was written —
                # an honestly empty role, never a HUMAN-stamped guess (contract §5.2). The person is
                # genuinely admitted and stays visible: its discovery-provenance + professional-fact
                # claims are durable and are carried in ``claim_refs``; only the six role fields are
                # absent, and it is counted in ``needs_review``.
                members.append(
                    CommitteeMemberRef(
                        contact_entity_id=contact_entity_id,
                        discovery_claim_id=outcome.discovery_claim_id,
                        professional_claim_ids=professional_claim_ids,
                    )
                )
                continue
            role_claim_id, persona_claim_id = role_ids
            members.append(
                CommitteeMemberRef(
                    contact_entity_id=contact_entity_id,
                    persona=verdict.role,
                    role_on_committee=verdict.role.value,
                    role_confidence=verdict.confidence,
                    role_plausible=verdict.plausible,
                    discovery_claim_id=outcome.discovery_claim_id,
                    role_claim_id=role_claim_id,
                    persona_claim_id=persona_claim_id,
                    professional_claim_ids=professional_claim_ids,
                )
            )

        rule.record(new_admits=new_admits, candidates_seen=seen_this_source, cost_cents=source_cost)
        reason = rule.reason()
        if reason is not None:
            stop_reason = reason
            break

    coverage = estimate_committee_coverage(
        channels_searched=channels_searched,
        all_channels=all_channels,
        stopping_reason=stop_reason,
        candidates_seen=candidates_seen_total,
        admitted=admitted,
    )
    return CommitteeResult(
        account_entity_id=account.id,
        members=tuple(members),
        coverage=coverage,
        cost_cents=total_cost,
        admitted=admitted,
        # Honest tally: every admitted member still awaiting a role judgment (all of them in
        # ``agent_deferred`` mode; the ungrounded ones in ``worker_llm``).
        needs_review=sum(1 for member in members if not member.has_role),
        dropped=dropped,
    )


class CommitteeAspectWorker:
    """Adapts :func:`discover_committee` to the M7 ``AspectWorker`` seam (``aspect='committee'``).

    The orchestrator hands an :class:`AspectContext` (no connection); the worker opens one from the
    injected ``ConnFactory`` and reads ``workspace_id``/``icp_key``/``icp_version`` from
    ``ctx.params`` (the phase-input escape hatch) to load the ICP spec + bind the tenant. Concrete
    ``CommitteeSource``s + the gateway + the role model are injected at the ``api`` composition
    root."""

    aspect = "committee"

    def __init__(
        self,
        *,
        session_factory: ConnFactory,
        sources: Sequence[CommitteeSource],
        gateway: LLMGateway,
        role_model: str | None = None,
        pre_spend_gate: PreSpendGate | None = None,
        config: CommitteeConfig = DEFAULT_COMMITTEE_CONFIG,
    ) -> None:
        self._session_factory = session_factory
        self._sources = sources
        self._gateway = gateway
        self._role_model = role_model
        self._pre_spend_gate = pre_spend_gate
        self._config = config

    async def research(self, ctx: AspectContext) -> WorkerResult:
        workspace_id = str(ctx.params["workspace_id"])
        icp_key = str(ctx.params["icp_key"])
        icp_version = int(ctx.params["icp_version"])  # type: ignore[arg-type]
        source_plan = ctx.params.get("source_plan")
        plan = [str(key) for key in source_plan] if isinstance(source_plan, (list, tuple)) else None

        async with self._session_factory() as conn:
            spec = await get_icp_version(conn, workspace_id, icp_key, icp_version)
            result = await discover_committee(
                conn,
                account_entity_id=ctx.entity_id,
                run_id=ctx.run_id,
                workspace_id=workspace_id,
                sources=self._sources,
                gateway=self._gateway,
                spec=spec,
                role_model=self._role_model,
                source_plan=plan,
                budget_cap_cents=ctx.budget_envelope_cents,
                pre_spend_gate=self._pre_spend_gate,
                config=self._config,
            )

        status = (
            WorkerStatus.BUDGET_EXCEEDED
            if result.coverage.stopping_reason is CommitteeStopReason.BUDGET_CAP
            else WorkerStatus.OK
        )
        return WorkerResult(
            aspect=self.aspect,
            status=status,
            claim_refs=result.claim_refs,
            cost_cents=result.cost_cents,
            detail={
                "admitted": result.admitted,
                "dropped": result.dropped,
                "needs_review": result.needs_review,
                "committee_coverage": result.coverage.model_dump(mode="json"),
            },
        )
