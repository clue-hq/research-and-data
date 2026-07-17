"""M12.3 — the output/handoff **service**: the transport-agnostic boundary to the content layer.

This is the place the research subsystem ends (overview §3). Everything upstream produces
``account_handoff`` objects; this module reads/serves them and drives the durable emit path — but it
is **transport-agnostic** (no FastAPI here): the HTTP surface is a thin adapter at the ``api``
composition root, and the push transport is the injected
:class:`~clue_research.narrative.publisher.HandoffPublisher`. Keeping the logic here (a
``narrative``
worker) means the seam can be served over REST pull, event push, or a D2 design-system adapter
without touching this code (M12.3 AC8).

It is a strict **read/emit projection** over the materialised handoffs (M12.2) — never a write-back
path from content/design into the claim store (substrate §5c / conventions §6): the only reads are
of
``account_handoff`` rows, the only writes are the assembler caching its own read + the
one-directional
``handoff_event`` outbox. Every read is **tenant-scoped** on ``client_id`` (a client's assembled
handoff is ``TENANT_PRIVATE`` even where underlying public claims are shared — substrate §2). Each
served object carries its ``schema_version`` (so a pinned consumer survives an additive schema
change
— AC5) and its **verification health** (the trust posture, Doc C §6).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    CampaignPhase,
    CampaignRunId,
    ClaimId,
    EntityId,
    Persona,
    ProvenanceRef,
    UnitInterval,
    UtcDatetime,
)
from clue_db import ConnFactory
from clue_research.narrative.handoff import AssembledHandoff, HandoffAssembler
from clue_research.narrative.handoff_events import (
    HandoffEvent,
    emit_handoff_event,
    handoff_ref_for,
)
from clue_research.narrative.handoff_store import (
    list_handoffs_for_run,
    read_handoff,
    write_handoff,
)
from clue_research.narrative.health import VerificationHealth
from clue_research.narrative.publisher import HandoffPublisher, OutboxHandoffPublisher
from clue_research.narrative.readiness import HandoffReadinessReader
from clue_research.obs import (
    ATTR_CAMPAIGN_RUN_ID,
    ATTR_CLIENT_ID,
    ATTR_ENTITY_ID,
    MetricSink,
    apply_attributes,
    get_metric_sink,
    traced_step,
)

# The served ``account_handoff`` contract version (M12.3). Bump the MINOR for an additive change (a
# new optional field), the MAJOR only for a breaking one; a pinned consumer reads the field off
# every
# response and keeps working across additive bumps (AC5). It is M12.3-owned config, not a core edit.
HANDOFF_SCHEMA_VERSION = "1.0"

SPAN_HANDOFF_SERVE = "narrative.handoff_serve"
SPAN_HANDOFF_LIST = "narrative.handoff_list"
SPAN_HANDOFF_EMIT = "narrative.handoff_emit"

METRIC_HANDOFFS_SERVED = "research.handoff.served"
METRIC_HANDOFFS_EMITTED = "research.handoff.emitted"
METRIC_HANDOFF_TIER4_PASS_RATE = "research.handoff.verification.tier4_pass_rate"
METRIC_HANDOFF_STRONG_BINDING_SHARE = "research.handoff.verification.strong_binding_share"


class HandoffNotFoundError(Exception):
    """A requested handoff (or a provenance entry within it) is not servable — either it is not yet
    assembled (the account has not reached the ``handoff`` phase) or it is not this tenant's. The
    HTTP adapter maps this to ``404``: a not-yet-ready account is indistinguishable from an absent
    one across the tenant boundary (never leak another tenant's existence, substrate §2)."""


class ProvenanceRefResponse(BaseModel):
    """One resolved provenance entry as the API serves it: the ``claim_id`` asked for + its source
    :class:`ProvenanceRef` (source_url / source_tier / evidence_span). Self-describing so the
    consumer need not correlate back to the request URL."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    provenance: ProvenanceRef


class ServedHandoff(BaseModel):
    """One handoff as the API serves it: the M12.2 :class:`AssembledHandoff` (the frozen
    ``AccountHandoff`` + the M12.2/M12.3 extras incl. ``verification_health``) stamped with the
    contract ``schema_version`` the consumer pins on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    assembled: AssembledHandoff


class HandoffSummary(BaseModel):
    """A compact per-account row in the list view (the full object is fetched per-account). Carries
    enough for the content layer to triage (scores, committee/persona/narrative presence, coverage,
    verification health) + the ``handoff_ref`` to fetch the full object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_entity_id: EntityId
    icp_spec_version: int
    icp_key: str
    tier: str | None
    fit_score: UnitInterval
    intent_score: UnitInterval
    fit_scored: bool
    intent_scored: bool
    non_fit: bool
    committee_size: int
    personas: tuple[Persona, ...]
    value_narrative_count: int
    coverage_confidence: UnitInterval | None
    verification_health: VerificationHealth | None
    assembled_at: UtcDatetime | None
    handoff_ref: str


class HandoffListPage(BaseModel):
    """The list-serve envelope for one campaign run: the run's readiness (so a consumer knows
    whether
    to keep polling) + the ready handoff summaries. ``run_phase`` is ``None`` when the run is
    unknown
    to this tenant (cross-tenant isolation: an empty page, never another tenant's existence)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    campaign_run_id: CampaignRunId
    run_phase: CampaignPhase | None
    run_is_terminal: bool
    total: int
    items: tuple[HandoffSummary, ...]


class EmitReport(BaseModel):
    """The result of an emit pass over a run's ready accounts (the durable outbox writes +
    pushes)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    campaign_run_id: CampaignRunId
    accounts_processed: int = 0
    newly_emitted: int = 0
    refs: tuple[str, ...] = ()


def _summary(icp_key: str, tier: str | None, assembled: AssembledHandoff) -> HandoffSummary:
    """Project an ``(icp_key, tier, AssembledHandoff)`` row to its compact list summary."""
    h = assembled.handoff
    version = h.icp_spec_version if h.icp_spec_version is not None else 0
    return HandoffSummary(
        account_entity_id=h.account_entity_id,
        icp_spec_version=version,
        icp_key=icp_key,
        tier=tier,
        fit_score=h.fit_score.value,
        intent_score=h.intent_score.value,
        fit_scored=assembled.fit_scored,
        intent_scored=assembled.intent_scored,
        non_fit=assembled.non_fit,
        committee_size=len(h.committee),
        personas=tuple(m.persona for m in h.committee),
        value_narrative_count=len(h.value_narrative),
        coverage_confidence=h.coverage_confidence,
        verification_health=assembled.verification_health,
        assembled_at=h.assembled_at,
        handoff_ref=handoff_ref_for(h.account_entity_id, version, icp_key),
    )


class HandoffService:
    """The transport-agnostic read API over assembled handoffs (M12.3). Constructed with the
    injected
    :class:`HandoffReadinessReader` (the M7 campaign-run phase seam) at the ``api`` root; all reads
    are pure, tenant-scoped store reads — no synthesis, no write-back."""

    def __init__(
        self,
        *,
        readiness_reader: HandoffReadinessReader | None = None,
        sink: MetricSink | None = None,
    ) -> None:
        self._readiness_reader = readiness_reader
        self._sink = sink

    def _sink_or_default(self) -> MetricSink:
        return self._sink or get_metric_sink()

    async def get_handoff(
        self,
        conn: AsyncConnection,
        *,
        client_id: str,
        account_entity_id: EntityId,
        icp_spec_version: int,
        icp_key: str = "",
    ) -> ServedHandoff:
        """Fetch one ``account_handoff`` for ``(client_id, account_entity_id, icp_spec_version,
        icp_key)`` including its ``provenance_index`` and ``verification_health``.

        Raises :class:`HandoffNotFoundError` if no row is materialised for the tenant (a
        not-yet-ready
        account and an absent one are deliberately indistinguishable across the tenant boundary)."""
        with traced_step(
            SPAN_HANDOFF_SERVE,
            **{ATTR_ENTITY_ID: str(account_entity_id), ATTR_CLIENT_ID: client_id},
        ):
            assembled = await read_handoff(
                conn,
                client_id=client_id,
                account_entity_id=account_entity_id,
                icp_spec_version=icp_spec_version,
                icp_key=icp_key,
            )
            if assembled is None:
                raise HandoffNotFoundError(
                    f"no handoff for account {account_entity_id} "
                    f"(icp_spec_version={icp_spec_version}, icp_key={icp_key!r}) in this tenant"
                )
            self._emit_health_metrics(assembled, client_id=client_id)
            return ServedHandoff(schema_version=HANDOFF_SCHEMA_VERSION, assembled=assembled)

    async def resolve_provenance(
        self,
        conn: AsyncConnection,
        *,
        client_id: str,
        account_entity_id: EntityId,
        icp_spec_version: int,
        claim_id: ClaimId,
        icp_key: str = "",
    ) -> ProvenanceRef:
        """Resolve one value's ``claim_id`` to its full provenance within a served handoff — the
        "every line is sourced" traversal (overview §3, AC1). Raises :class:`HandoffNotFoundError`
        if
        the handoff is not servable or the ``claim_id`` is not in its provenance index."""
        assembled = await read_handoff(
            conn,
            client_id=client_id,
            account_entity_id=account_entity_id,
            icp_spec_version=icp_spec_version,
            icp_key=icp_key,
        )
        if assembled is None:
            raise HandoffNotFoundError(f"no handoff for account {account_entity_id} in this tenant")
        ref = assembled.handoff.provenance_index.get(str(claim_id))
        if ref is None:
            raise HandoffNotFoundError(
                f"claim {claim_id} is not in the provenance index of this handoff"
            )
        return ref

    async def list_handoffs(
        self,
        conn: AsyncConnection,
        *,
        client_id: str,
        campaign_run_id: CampaignRunId,
        tier: str | None = None,
        persona: Persona | None = None,
        min_verification_pass_rate: UnitInterval | None = None,
    ) -> HandoffListPage:
        """List the **ready** handoffs for a campaign run (only materialised → only handoff-phase
        accounts; an account in deep/verification is absent — AC2). Tenant-scoped on ``client_id``;
        a run unknown to this tenant yields an empty page with ``run_phase=None`` (no cross-tenant
        leak). Optional filters (spec §M12.3): ``tier`` (the account's research tier), ``persona``
        (presence in the committee), and ``min_verification_pass_rate`` (the tier-4 judge pass-rate
        floor)."""
        with traced_step(
            SPAN_HANDOFF_LIST,
            **{ATTR_CAMPAIGN_RUN_ID: str(campaign_run_id), ATTR_CLIENT_ID: client_id},
        ):
            run_phase: CampaignPhase | None = None
            run_terminal = False
            if self._readiness_reader is not None:
                readiness = await self._readiness_reader.run_readiness(
                    campaign_run_id=campaign_run_id, client_id=client_id
                )
                if readiness is not None:
                    run_phase = readiness.phase
                    run_terminal = readiness.is_terminal
            assembled_rows = await list_handoffs_for_run(
                conn, client_id=client_id, campaign_run_id=campaign_run_id
            )
            summaries = [
                _summary(icp_key, row_tier, a)
                for icp_key, row_tier, a in assembled_rows
                if _passes_filters(a, row_tier, tier, persona, min_verification_pass_rate)
            ]
            return HandoffListPage(
                schema_version=HANDOFF_SCHEMA_VERSION,
                campaign_run_id=campaign_run_id,
                run_phase=run_phase,
                run_is_terminal=run_terminal,
                total=len(summaries),
                items=tuple(summaries),
            )

    def _emit_health_metrics(self, assembled: AssembledHandoff, *, client_id: str) -> None:
        """Emit per-served-object verification-health gauges (Doc C §6) → M13.4's surface."""
        sink = self._sink_or_default()
        attrs = {
            ATTR_ENTITY_ID: str(assembled.handoff.account_entity_id),
            ATTR_CLIENT_ID: client_id,
        }
        sink.add(METRIC_HANDOFFS_SERVED, 1, attrs)
        vh = assembled.verification_health
        if vh is None:
            return
        if vh.tier4_judge_pass_rate is not None:
            sink.gauge(METRIC_HANDOFF_TIER4_PASS_RATE, vh.tier4_judge_pass_rate, attrs)
        if vh.strong_binding_share is not None:
            sink.gauge(METRIC_HANDOFF_STRONG_BINDING_SHARE, vh.strong_binding_share, attrs)


def _passes_filters(
    assembled: AssembledHandoff,
    row_tier: str | None,
    tier: str | None,
    persona: Persona | None,
    min_verification_pass_rate: UnitInterval | None,
) -> bool:
    """Apply the optional list filters (tier; persona presence in the committee; verification
    pass-rate floor). A ``tier`` filter excludes a handoff whose tier is unknown (``None``); a
    pass-rate floor excludes a handoff whose rate is unknown (``None``) — both conservative."""
    if tier is not None and row_tier != tier:
        return False
    if persona is not None and persona not in {m.persona for m in assembled.handoff.committee}:
        return False
    if min_verification_pass_rate is not None:
        vh = assembled.verification_health
        rate = vh.tier4_judge_pass_rate if vh is not None else None
        if rate is None or rate < min_verification_pass_rate:
            return False
    return True


async def emit_ready_handoffs(
    *,
    conn_factory: ConnFactory,
    assembler: HandoffAssembler,
    readiness_reader: HandoffReadinessReader,
    publisher: HandoffPublisher | None = None,
    campaign_run_id: CampaignRunId,
    client_id: str,
    assembled_at: UtcDatetime,
    coverage_confidence: UnitInterval | None = None,
    sink: MetricSink | None = None,
) -> EmitReport:
    """Assemble + materialise + emit a durable ``handoff_event`` for every account in
    ``campaign_run_id``
    that has reached handoff-readiness — the emit path the campaign-run state machine fires when it
    enters the ``handoff`` phase (M12.3 emit/notify).

    Idempotent: each account's emit is ``ON CONFLICT DO NOTHING`` on
    ``(campaign_run, account, icp_spec_version, icp_key)``, so a re-entry / crash-resume never
    double-emits; the optional :class:`HandoffPublisher` push fires exactly once per *newly* emitted
    row, **after** the per-account transaction commits (so a roll-back never leaves a phantom push).
    Materialisation is the M12.2 ``write_handoff`` UPSERT (recompute-on-supersede). The ICP segment
    coordinates are read off the run (``RunReadiness.icp_key`` / ``.icp_version``) so segment A
    never
    assembles under segment B's version (D5). A run unknown to this tenant returns an empty
    report."""
    publisher = publisher or OutboxHandoffPublisher()
    sink = sink or get_metric_sink()
    with traced_step(
        SPAN_HANDOFF_EMIT,
        **{ATTR_CAMPAIGN_RUN_ID: str(campaign_run_id), ATTR_CLIENT_ID: client_id},
    ) as span:
        readiness = await readiness_reader.run_readiness(
            campaign_run_id=campaign_run_id, client_id=client_id
        )
        if readiness is None:
            return EmitReport(campaign_run_id=campaign_run_id)
        accounts = await readiness_reader.ready_accounts(
            campaign_run_id=campaign_run_id, client_id=client_id
        )
        icp_key = readiness.icp_key
        icp_version = readiness.icp_version
        processed = 0
        newly = 0
        refs: list[str] = []
        for acc in accounts:
            if not acc.is_ready:
                continue
            event, was_new = await _assemble_materialise_emit(
                conn_factory=conn_factory,
                assembler=assembler,
                campaign_run_id=campaign_run_id,
                client_id=client_id,
                account_entity_id=acc.account_entity_id,
                icp_version=icp_version,
                icp_key=icp_key,
                tier=acc.tier,
                assembled_at=assembled_at,
                coverage_confidence=coverage_confidence,
            )
            processed += 1
            if was_new:
                await publisher.publish(event)  # after-commit, exactly once
                newly += 1
                refs.append(event.handoff_ref)
        apply_attributes(span, {"narrative.handoff.emitted": newly})
        sink.add(METRIC_HANDOFFS_EMITTED, newly, {ATTR_CAMPAIGN_RUN_ID: str(campaign_run_id)})
        return EmitReport(
            campaign_run_id=campaign_run_id,
            accounts_processed=processed,
            newly_emitted=newly,
            refs=tuple(refs),
        )


async def _assemble_materialise_emit(
    *,
    conn_factory: ConnFactory,
    assembler: HandoffAssembler,
    campaign_run_id: CampaignRunId,
    client_id: str,
    account_entity_id: EntityId,
    icp_version: int,
    icp_key: str,
    tier: str | None,
    assembled_at: UtcDatetime,
    coverage_confidence: UnitInterval | None,
) -> tuple[HandoffEvent, bool]:
    """Assemble + materialise one account's handoff and write its outbox row in one transaction;
    return the :class:`HandoffEvent` and whether it was newly emitted (the push fires after
    commit)."""
    event = HandoffEvent(
        campaign_run_id=campaign_run_id,
        account_entity_id=account_entity_id,
        icp_spec_version=icp_version,
        icp_key=icp_key,
        client_id=client_id,
        handoff_ref=handoff_ref_for(account_entity_id, icp_version, icp_key),
        schema_version=HANDOFF_SCHEMA_VERSION,
    )
    async with conn_factory() as conn:
        assembled = await assembler.assemble(
            conn,
            account_entity_id,
            icp_spec_version=icp_version,
            client_id=client_id,
            assembled_at=assembled_at,
            icp_key=icp_key,
            campaign_run_id=campaign_run_id,
            coverage_confidence=coverage_confidence,
        )
        await write_handoff(conn, assembled, client_id=client_id, icp_key=icp_key, tier=tier)
        was_new = await emit_handoff_event(conn, event)
    return event, was_new


# Re-exported for callers that build their own emit loops (kept narrow on purpose).
__all__ = [
    "HANDOFF_SCHEMA_VERSION",
    "HandoffService",
    "HandoffNotFoundError",
    "ServedHandoff",
    "ProvenanceRefResponse",
    "HandoffSummary",
    "HandoffListPage",
    "EmitReport",
    "emit_ready_handoffs",
    "SPAN_HANDOFF_SERVE",
    "SPAN_HANDOFF_LIST",
    "SPAN_HANDOFF_EMIT",
    "METRIC_HANDOFFS_SERVED",
    "METRIC_HANDOFFS_EMITTED",
    "METRIC_HANDOFF_TIER4_PASS_RATE",
    "METRIC_HANDOFF_STRONG_BINDING_SHARE",
]
