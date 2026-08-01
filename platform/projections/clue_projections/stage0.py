"""C4 Stage-0 read models. Every query is workspace-scoped and side-effect free.

Two families live here:

* the original C4 inspection views (``recon_brief`` / ``stage0_progress`` / ``stage0_readiness``);
* the **PC-C8 Stage-0 project card** (``compile_stage0_project_card``) — the single hard-bounded L3
  projection of current effective project state that replaced the two raw ``to_jsonb(row)``
  snapshots the agent used to be handed. Doc A Part III specifies L3 as a *"project state card …
  [from the] projection API"*; the card is that contract made real.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    EntityId,
    ReadinessDecisionId,
    ReadinessGate,
    ReadinessVerdict,
    ReconRunId,
    VolunteeredStatementId,
)
from clue_db import ConnFactory, transaction
from clue_research.stage0 import (
    CLIENT_KNOWLEDGE_FIELDS,
    MAX_PROJECT_STATEMENTS,
    ReadinessDecisionRow,
    StatementRoute,
    VolunteeredStatementRow,
    get_readiness_decision,
    get_recon,
    read_client_kb,
    read_client_kb_claims,
    read_readiness_decisions,
    read_statements,
)


class ReconBriefView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    recon_run_id: str
    client_entity_id: str | None
    client_kb_version: int | None
    product_id: str | None
    facts: dict[str, JsonValue]
    fast_cost_cents: str
    background_pending: bool


class Stage0ProgressView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    recon_run_id: str
    fast_status: str
    background_status: str
    fast_client_kb_version: int | None
    client_kb_version: int | None
    fast_run_id: str
    background_run_id: str
    failure_code: str | None
    gap_refs: tuple[dict[str, JsonValue], ...] = ()
    field_proposal_refs: tuple[str, ...] = ()
    source_proposal_refs: tuple[str, ...] = ()
    ingestion_refs: tuple[str, ...] = ()


class Stage0ReadinessView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    readiness_decision_id: str
    gate: str
    verdict: str
    effective_verdict: str
    spec_version: int
    reason_codes: tuple[str, ...]
    metrics: dict[str, JsonValue]
    gap_refs: tuple[dict[str, JsonValue], ...]
    field_proposal_refs: tuple[str, ...]
    source_proposal_refs: tuple[str, ...]
    ingestion_refs: tuple[str, ...]
    agent_sufficiency_status: str


async def recon_brief(
    *,
    recon_run_id: ReconRunId,
    workspace_id: str,
    conn_factory: ConnFactory = transaction,
) -> ReconBriefView | None:
    async with conn_factory() as conn:
        recon = await get_recon(conn, recon_run_id, workspace_id=workspace_id)
        if recon is None:
            return None
        facts: dict[str, JsonValue] = {}
        if recon.client_entity_id is not None and recon.fast_client_kb_version is not None:
            facts = await read_client_kb(
                conn,
                recon.client_entity_id,
                workspace_id=workspace_id,
                version=recon.fast_client_kb_version,
                product_id=recon.product_id,
            )
    return ReconBriefView(
        recon_run_id=str(recon.id),
        client_entity_id=(
            str(recon.client_entity_id) if recon.client_entity_id is not None else None
        ),
        client_kb_version=recon.fast_client_kb_version,
        product_id=recon.product_id,
        facts=facts,
        fast_cost_cents=str(recon.fast_cost_cents),
        background_pending=recon.background_status.value in {"queued", "running", "paused"},
    )


async def stage0_progress(
    *,
    recon_run_id: ReconRunId,
    workspace_id: str,
    conn_factory: ConnFactory = transaction,
) -> Stage0ProgressView | None:
    async with conn_factory() as conn:
        recon = await get_recon(conn, recon_run_id, workspace_id=workspace_id)
        decision = None
        if recon is not None and recon.project_id is not None:
            decision_id = (
                await conn.execute(
                    text(
                        "SELECT id FROM readiness_decision "
                        "WHERE workspace_id = :workspace_id AND project_id = :project_id "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {
                        "workspace_id": workspace_id,
                        "project_id": recon.project_id,
                    },
                )
            ).scalar_one_or_none()
            if decision_id is not None:
                decision = await get_readiness_decision(
                    conn, ReadinessDecisionId(decision_id), workspace_id=workspace_id
                )
    if recon is None:
        return None
    return Stage0ProgressView(
        recon_run_id=str(recon.id),
        fast_status=recon.fast_status.value,
        background_status=recon.background_status.value,
        fast_client_kb_version=recon.fast_client_kb_version,
        client_kb_version=recon.client_kb_version,
        fast_run_id=str(recon.fast_run_id),
        background_run_id=str(recon.background_run_id),
        failure_code=recon.failure_code,
        gap_refs=decision.gap_refs if decision is not None else (),
        field_proposal_refs=decision.field_proposal_refs if decision is not None else (),
        source_proposal_refs=decision.source_proposal_refs if decision is not None else (),
        ingestion_refs=decision.ingestion_refs if decision is not None else (),
    )


async def readiness_override_refs(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    decision_ids: Sequence[ReadinessDecisionId],
) -> dict[str, str]:
    """``{decision_id: override_id}`` for the decisions carrying a human just-go override.

    The one override join on the read side. ``stage0_readiness`` (single decision) and the PC-C8
    project card (latest-per-gate) both go through it, so the two surfaces cannot drift on what
    "overridden" means — the C8 spec §4 requirement that the card *reuses* rather than re-derives
    this logic. A decision with no override is simply absent from the mapping.
    """

    if not decision_ids:
        return {}
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT readiness_decision_id, id FROM readiness_override "
                    "WHERE workspace_id = :workspace_id "
                    "AND readiness_decision_id = ANY(CAST(:ids AS uuid[]))"
                ),
                {
                    "workspace_id": workspace_id,
                    "ids": [str(item) for item in decision_ids],
                },
            )
        )
        .mappings()
        .all()
    )
    return {str(row["readiness_decision_id"]): str(row["id"]) for row in rows}


def effective_readiness_verdict(verdict: str, *, override_ref: str | None) -> str:
    """The verdict a human surface should act on: a just-go override outranks the machine verdict.

    Shared by ``stage0_readiness`` and the project card (see :func:`readiness_override_refs`).
    """

    return ReadinessVerdict.OVERRIDDEN.value if override_ref is not None else verdict


async def stage0_readiness(
    *,
    readiness_decision_id: ReadinessDecisionId,
    workspace_id: str,
    conn_factory: ConnFactory = transaction,
) -> Stage0ReadinessView | None:
    async with conn_factory() as conn:
        decision = await get_readiness_decision(
            conn, readiness_decision_id, workspace_id=workspace_id
        )
        if decision is None:
            return None
        overrides = await readiness_override_refs(
            conn, workspace_id=workspace_id, decision_ids=(readiness_decision_id,)
        )
    return Stage0ReadinessView(
        readiness_decision_id=str(decision.id),
        gate=decision.gate.value,
        verdict=decision.verdict.value,
        effective_verdict=effective_readiness_verdict(
            decision.verdict.value,
            override_ref=overrides.get(str(decision.id)),
        ),
        spec_version=decision.spec_version,
        reason_codes=decision.reason_codes,
        metrics=decision.metrics,
        gap_refs=decision.gap_refs,
        field_proposal_refs=decision.field_proposal_refs,
        source_proposal_refs=decision.source_proposal_refs,
        ingestion_refs=decision.ingestion_refs,
        agent_sufficiency_status=decision.agent_sufficiency_status,
    )


# =============================================================================
# PC-C8 — the Stage-0 project card
# =============================================================================

STAGE0_PROJECT_CARD_MEDIA_TYPE = "application/vnd.clue.stage0-project-card+json"
STAGE0_CARD_SCHEMA_VERSION = "1"
STAGE0_CARD_KIND = "stage0_project"

#: The verdict a gate carries when no *authoritative, lineage-current* decision exists for it.
#: Deliberately not a :class:`~clue_core.ReadinessVerdict` member: it is the honest absence of a
#: verdict, not a fourth verdict, and the card must never show a stale one instead (spec §4).
NOT_EVALUATED_FOR_CURRENT_LINEAGE = "not_evaluated_for_current_lineage"

#: The one selection order the compiler implements, named in the card so a reader knows what the
#: bound dropped: exact ``(route_key, quote)`` duplicates collapse, corrections have already
#: superseded what they replace upstream (``read_statements``), and the newest survive the cap.
STATEMENT_SELECTION_ORDER = "dedup_supersession_newest_first"


class Stage0CardPolicy(BaseModel):
    """The versioned, data-not-code size policy the card compiler enforces (spec §3.1).

    Every cap is byte-denominated: these bound *storage and serialization*, not tokenization (the
    layer budget's tokenizer swap is a separate slice). ``version`` participates in the card bytes,
    so changing a cap is a visible card change — a policy edit can never silently reshape context.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "stage0-card-policy-v1"
    #: Aligned with ``MAX_PROJECT_STATEMENTS`` — one number, one rationale: the card shows exactly
    #: as many statements as one ICP synthesis may read.
    max_statements: int = MAX_PROJECT_STATEMENTS
    max_quote_bytes: int = 1_000
    max_quote_total_bytes: int = 16_000
    #: Per-gate ``metrics`` + ``reason_codes``. Readiness evidence is caller-supplied and
    #: unbounded at the source, so without this cap it *inverts the shed order*: three gates
    #: carrying 6 KB of metrics each would shed every statement and produce a zero-quote card —
    #: precisely the unreadable-context defect this slice exists to fix. Readiness must never
    #: starve the interview section, so it is bounded before the whole-card fit runs.
    max_gate_evidence_bytes: int = 1_000
    max_kb_brief_bytes: int = 256
    max_kb_total_bytes: int = 4_000
    #: Forward capacity, not a load-bearing bound: :class:`Stage0CardOmissionKind` can produce at
    #: most four entries in v1, so ``OMISSIONS_TRUNCATED`` is unreachable in production and only
    #: the tests (which lower this cap) exercise the collapse. Nothing should treat 12 as tuned.
    max_omissions: int = 12
    max_card_bytes: int = 24_000


STAGE0_CARD_POLICY_V1 = Stage0CardPolicy()


class Stage0CardOmissionKind(StrEnum):
    """What a card left out — typed kinds only.

    Never a tool name: the resource manifest owns the effective tool surface, so a card can never
    advertise a capability the profile does not install (spec §3/§7).
    """

    STATEMENTS_OVER_CAP = "statements_over_cap"
    EXCLUDED_STATEMENT_EVIDENCE_MISSING = "excluded_statement_evidence_missing"
    READINESS_HISTORY = "readiness_history"
    CLIENT_KNOWLEDGE_OVER_CAP = "client_knowledge_over_cap"
    OMISSIONS_TRUNCATED = "omissions_truncated"


class ExcludedEvidenceReason(StrEnum):
    """Why a statement's words could not be shown."""

    #: The captured onboarding artifact is gone — DSAR erasure, tombstone, or a purged row. Honest
    #: absence, never fatal: erasing one turn must not disable the whole projection.
    ARTIFACT_MISSING = "artifact_missing"


class ResolvedQuote(BaseModel):
    """One statement's exact captured words, sliced from its artifact and hash-verified."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    statement_id: VolunteeredStatementId
    quote: str


class ExcludedEvidence(BaseModel):
    """A statement whose evidence could not be read. Surfaced in ``omissions``, never dropped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    statement_id: VolunteeredStatementId
    reason: ExcludedEvidenceReason


class StatementEvidenceReader(Protocol):
    """The projection's evidence port (spec §4).

    A connection alone cannot resolve a quote: ``volunteered_statement`` stores offsets plus a
    sha256 into a captured artifact and *no text*, so reading the words needs artifact bytes. The
    projection layer may not import storage, so it declares the port and the ``clue_api``
    composition root injects the artifact-backed implementation.

    The implementation owns: workspace validation; missing/tombstoned evidence (→
    :class:`ExcludedEvidence`); content-sha and quote-sha verification; UTF-8 offset semantics;
    bounded reads. Integrity failures (a span that does not hash to the recorded quote, a
    cross-workspace artifact reference) **raise** — corruption and scoping violations are not
    erasure and must not be laundered into a quiet omission.

    ``resolve_quotes`` is the batch form the compiler uses (one connection, one body cache for a
    whole card); ``resolve_quote`` is the single-statement form. Both must agree.
    """

    async def resolve_quote(
        self, *, workspace_id: str, statement: VolunteeredStatementRow
    ) -> ResolvedQuote | ExcludedEvidence: ...

    async def resolve_quotes(
        self, *, workspace_id: str, statements: Sequence[VolunteeredStatementRow]
    ) -> tuple[ResolvedQuote | ExcludedEvidence, ...]: ...


class Stage0CardProject(BaseModel):
    """The project this turn is about, including the client entity its claims are keyed on.

    ``client_entity_id`` is here for one concrete reason (PC-C8 §8, v2.2): a ``claim``-route
    statement is refused without an ``entity_id`` (``InterviewStatement._route_shape``), and after
    the task-1.3 delta the card is the *only* place the model can read the client's entity id — the
    tool field became engine-injected authority and the stage snapshot that used to state it was
    deleted. Without it the model must either skip claim routing or invent a UUID.

    Showing an id is not authorizing it: the id is trusted-but-visible scope, the way
    ``project_id``/``brand_id`` already are. Task 1.4 moves the *authorship* engine-side (defaulting
    ``entity_id`` from the constitution and existence-checking it), after which this field is
    orientation rather than a load-bearing input — kept either way, because a model reasoning about
    "facts about the client" should be able to name what the client is.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str
    name: str
    workspace_id: str
    brand_id: str
    client_entity_id: str


class Stage0CardProduct(BaseModel):
    """The project's product. ``confirmed`` is false while only a *candidate* exists."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    product_id: str | None = None
    name: str | None = None
    confirmed: bool


class Stage0CardKnownField(BaseModel):
    """One Client-KB field as a bounded brief plus the claim ref that proves it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    brief_value: str
    claim_id: str
    brief_truncated: bool


class Stage0CardClientKnowledge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int
    known_fields: tuple[Stage0CardKnownField, ...]
    open_gaps: tuple[str, ...]


class Stage0CardStatement(BaseModel):
    """One current-effective interview statement, with the words the model needs to reason."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    statement_id: str
    route_key: str
    route_kind: str
    quoted_text: str
    quote_truncated: bool
    supersedes: str | None = None


class Stage0CardSelection(BaseModel):
    """Honesty about the bound: how many of the candidates actually made it in.

    Every reduction between the durable rows and the shown ones is accounted for, so a reader can
    close the books rather than infer::

        included + statements_over_cap + deduped_count + excluded_statement_evidence_missing
            == live project_state statements

    ``total_effective`` is the post-dedup, evidence-resolved candidate pool the cap was applied to;
    ``deduped_count`` is what collapsed *before* that pool, which would otherwise vanish from the
    card's arithmetic entirely.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    included: int
    total_effective: int
    deduped_count: int
    order: str = STATEMENT_SELECTION_ORDER
    cursor: str | None = None


class Stage0CardInterview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    current_effective_statements: tuple[Stage0CardStatement, ...]
    selection: Stage0CardSelection
    unmapped_count: int
    superseded_count: int


class Stage0CardDecisionLineage(BaseModel):
    """A readiness lineage tuple. Which lineage depends on whether the gate has a decision:

    * on a gate **with** a ``decision_id`` — the immutable context that decision was taken
      against, read off the decision row;
    * on a ``not_evaluated_for_current_lineage`` gate (no ``decision_id``) — the project's
      *currently pinned* lineage, i.e. what a decision would have to match to count as current.
      Showing it is the useful half of the honest absence: it says what changed underneath.

    ``decision_id`` present-or-absent is the discriminator; the two senses are never mixed in one
    entry. (Kept as one field because the spec §3 schema names it once and both senses answer the
    same reader question — "which lineage are we talking about?")
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_kb_version: int | None = None
    product_id: str | None = None
    icp_key: str | None = None
    icp_version: int | None = None
    spec_version: int | None = None


class Stage0CardGateReadiness(BaseModel):
    """One gate's current standing. ``metrics``/``reason_codes`` are bounded evidence, not the row.

    ``evidence_truncated`` says the decision carried more than the policy's per-gate byte cap
    allows, so what is shown is a subset; the full row is reachable through the readiness-history
    cursor. Bounding here is what stops caller-supplied metrics from starving the interview
    section when the whole-card fit runs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate: str
    decision_id: str | None = None
    verdict: str
    effective_verdict: str
    override_ref: str | None = None
    decision_lineage: Stage0CardDecisionLineage
    metrics: dict[str, JsonValue] = {}
    reason_codes: tuple[str, ...] = ()
    evidence_truncated: bool = False


class Stage0CardReadiness(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    latest_by_gate: tuple[Stage0CardGateReadiness, ...]
    ledger_length: int


class Stage0CardIcpRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    icp_key: str
    version: int


class Stage0CardIcp(BaseModel):
    """Confirmed refs plus staleness booleans — never proposal bodies (spec §5.1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    confirmed: tuple[Stage0CardIcpRef, ...]
    proposals_pending: bool
    proposals_stale: bool


class Stage0CardOmission(BaseModel):
    """Kind + count + cursor. Never an id list, never a tool name."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Stage0CardOmissionKind
    count: int
    cursor: str | None = None


class Stage0CardLineage(BaseModel):
    """Real compile lineage. ``project`` has no version column, so none is invented."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_kb_version: int
    statement_selection_digest: str
    readiness_decision_ids: tuple[str, ...]
    confirmed_icps: tuple[Stage0CardIcpRef, ...]
    compiler_policy_version: str


class Stage0ProjectCard(BaseModel):
    """The hard-bounded L3 projection of current effective Stage-0 project state.

    Serialized canonically (:meth:`canonical_bytes`): sorted keys, ``exclude_none``,
    ``ensure_ascii=False``, no NaN. Identical durable state plus an identical policy version
    therefore produce byte-identical bytes and the same sha256 — content-addressed dedup and
    deterministic context receipts. Turn identity is deliberately *not* in the card (spec §2/§6),
    which is what makes that reuse real across turns.

    **``schema_version`` policy.** It stays ``"1"`` while the card only *grows* fields, because
    nothing reads the card by schema version yet: the sole consumers are the L3 assembler (which
    hands the bytes to a model) and this module's own validation, and a model reading one more
    key needs no migration. ``project.client_entity_id`` (PC-C8 §8 v2.2) is such a growth. Bump it
    when a field is removed, renamed, or changes meaning — an omission or a re-typed value is what
    would actually break a reader. Either way the bytes change, so the content address changes and
    a stale card is never mistaken for a current one; ``compiler_policy_version`` covers *bound*
    changes on the same schema.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = STAGE0_CARD_SCHEMA_VERSION
    card_kind: str = STAGE0_CARD_KIND
    compiler_policy_version: str
    project: Stage0CardProject
    product: Stage0CardProduct
    registered_client_claim_fields: tuple[str, ...]
    client_knowledge: Stage0CardClientKnowledge
    interview: Stage0CardInterview
    readiness: Stage0CardReadiness
    icp: Stage0CardIcp
    omissions: tuple[Stage0CardOmission, ...]
    compiled_from: Stage0CardLineage

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.model_dump(mode="json", exclude_none=True))

    def content_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class Stage0CardTooLarge(RuntimeError):
    """The compiler could not fit the card under its policy cap even after every reduction.

    The genuine-bug backstop, reached only when the sections the compiler *cannot* shed — the
    identity frame, the registered-field allowlist, the open-gap list, the bounded readiness
    entries, the omission counters — already exceed ``max_card_bytes`` on their own. That is a
    policy/schema mismatch to fix, not a condition a conversation can reach: the shed loop drops
    statements and then Client-KB fields, and the per-gate evidence cap keeps readiness from
    growing without bound (the one runtime path that used to reach here).
    """


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def encode_card_cursor(payload: dict[str, JsonValue]) -> str:
    """Encode one opaque, deterministic pagination cursor for a card omission (spec §7).

    Same encoding the bounded inspection tools accept, so an omission entry is directly resolvable
    without the card ever naming the tool that resolves it. Deterministic: identical durable state
    yields an identical cursor, which is what keeps the whole card content-addressable.
    """

    return base64.urlsafe_b64encode(_canonical_json(payload)).decode().rstrip("=")


def decode_card_cursor(cursor: str) -> dict[str, JsonValue]:
    """Inverse of :func:`encode_card_cursor` (the inspection tools' entry point)."""

    padded = cursor + "=" * (-len(cursor) % 4)
    decoded = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    if not isinstance(decoded, dict):
        raise ValueError("card cursor payload must be an object")
    return decoded


def _truncate_utf8(value: str, limit: int) -> tuple[str, bool]:
    """Truncate to ``limit`` **bytes** at a UTF-8 character boundary. Never splits a codepoint."""

    raw = value.encode()
    if len(raw) <= limit:
        return value, False
    cut = raw[:limit]
    while cut:
        try:
            return cut.decode(), True
        except UnicodeDecodeError:
            cut = cut[:-1]
    return "", True


def _brief(value: JsonValue) -> str:
    """Render a claim value as a short human string without inventing structure."""

    if isinstance(value, str):
        return value
    return _canonical_json(value).decode()


def _dedup_statements(
    rows: Sequence[VolunteeredStatementRow], quotes: dict[str, str]
) -> list[VolunteeredStatementRow]:
    """Collapse exact ``(route_key, quote)`` repeats to their first occurrence.

    The same rule ``icp_synthesis._bounded_statements`` applies: a client who says the same thing
    twice should not weigh twice, and the card should not spend its byte budget saying it twice.
    """

    seen: set[tuple[str, str]] = set()
    unique: list[VolunteeredStatementRow] = []
    for row in rows:
        key = (row.route_key, quotes[str(row.id)])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _statement_entry(
    row: VolunteeredStatementRow, quote: str, *, policy: Stage0CardPolicy
) -> Stage0CardStatement:
    text_value, truncated = _truncate_utf8(quote, policy.max_quote_bytes)
    return Stage0CardStatement(
        statement_id=str(row.id),
        route_key=row.route_key,
        route_kind=row.route_kind.value,
        quoted_text=text_value,
        quote_truncated=truncated,
        supersedes=str(row.correction_of_id) if row.correction_of_id is not None else None,
    )


def _select_statements(
    candidates: Sequence[VolunteeredStatementRow],
    quotes: dict[str, str],
    *,
    policy: Stage0CardPolicy,
    limit: int,
) -> tuple[Stage0CardStatement, ...]:
    """Newest-first up to ``limit``, also honouring the aggregate quoted-text cap.

    ``candidates`` arrives oldest-first (``read_statements`` order) and already deduped. The newest
    statements are the ones an ICP should follow, so they survive the cap; the card is emitted
    newest-first so the order it names is the order it shows.
    """

    selected: list[Stage0CardStatement] = []
    quote_bytes = 0
    for row in reversed(candidates):
        if len(selected) >= limit:
            break
        entry = _statement_entry(row, quotes[str(row.id)], policy=policy)
        size = len(entry.quoted_text.encode())
        if quote_bytes + size > policy.max_quote_total_bytes:
            break
        quote_bytes += size
        selected.append(entry)
    return tuple(selected)


def _statement_cursor(entries: Sequence[Stage0CardStatement]) -> str:
    """A keyset cursor at the oldest *included* statement — everything older is what was cut.

    One boundary id, never the list of ids the card left out: the cursor's job is to let the
    bounded inspection tool resume, not to smuggle the omitted rows back into the prompt.
    """

    payload: dict[str, JsonValue] = {"kind": "statements"}
    if entries:
        payload["before_statement_id"] = entries[-1].statement_id
    return encode_card_cursor(payload)


def _statement_digest(entries: Sequence[Stage0CardStatement]) -> str:
    """Canonical digest of exactly the statement ids that entered the card."""

    payload = _canonical_json([entry.statement_id for entry in entries])
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _known_fields(
    claims: Mapping[str, Claim], *, policy: Stage0CardPolicy, limit: int
) -> tuple[tuple[Stage0CardKnownField, ...], tuple[str, ...]]:
    """Bounded Client-KB briefs in field-registry order, plus the gaps that remain open.

    A brief is a *reading aid*, not the claim: the ``claim_id`` beside it is how a reader gets the
    exact value with its provenance, which is why truncating a brief loses nothing recoverable.
    ``limit`` bounds the number of *emitted* fields (not registry positions), so the compiler's
    fit loop can shed exactly one field at a time. ``open_gaps`` is unaffected by the cap: a gap is
    a field with no claim, which is true whether or not the card had room to show its neighbours.
    """

    fields: list[Stage0CardKnownField] = []
    total = 0
    for field_key in CLIENT_KNOWLEDGE_FIELDS:
        if len(fields) >= limit:
            break
        claim = claims.get(field_key)
        if claim is None:
            continue
        brief, truncated = _truncate_utf8(_brief(claim.value_json), policy.max_kb_brief_bytes)
        entry = Stage0CardKnownField(
            field=field_key,
            brief_value=brief,
            claim_id=str(claim.id),
            brief_truncated=truncated,
        )
        size = len(_canonical_json(entry.model_dump(mode="json", exclude_none=True)))
        if total + size > policy.max_kb_total_bytes:
            break
        total += size
        fields.append(entry)
    gaps = tuple(key for key in CLIENT_KNOWLEDGE_FIELDS if key not in claims)
    return tuple(fields), gaps


def _card_omissions(
    *,
    policy: Stage0CardPolicy,
    statements_dropped: int,
    statement_cursor: str | None,
    evidence_excluded: int,
    readiness_history: int,
    client_knowledge_withheld: int,
    client_kb_version: int,
) -> tuple[Stage0CardOmission, ...]:
    """Everything this card left out, as typed kinds + counts + cursors.

    No id lists and no tool names: the cursor lets a bounded inspection tool resume, and the
    resource manifest — not the card — decides which tool is installed to accept it (spec §3/§7).
    """

    entries: list[Stage0CardOmission] = []
    if statements_dropped:
        entries.append(
            Stage0CardOmission(
                kind=Stage0CardOmissionKind.STATEMENTS_OVER_CAP,
                count=statements_dropped,
                cursor=statement_cursor,
            )
        )
    if evidence_excluded:
        entries.append(
            Stage0CardOmission(
                kind=Stage0CardOmissionKind.EXCLUDED_STATEMENT_EVIDENCE_MISSING,
                count=evidence_excluded,
                cursor=encode_card_cursor({"kind": "excluded_statement_evidence"}),
            )
        )
    if readiness_history:
        entries.append(
            Stage0CardOmission(
                kind=Stage0CardOmissionKind.READINESS_HISTORY,
                count=readiness_history,
                cursor=encode_card_cursor({"kind": "readiness_history"}),
            )
        )
    if client_knowledge_withheld:
        entries.append(
            Stage0CardOmission(
                kind=Stage0CardOmissionKind.CLIENT_KNOWLEDGE_OVER_CAP,
                count=client_knowledge_withheld,
                cursor=encode_card_cursor(
                    {"kind": "client_knowledge", "client_kb_version": client_kb_version}
                ),
            )
        )
    if len(entries) <= policy.max_omissions:
        return tuple(entries)
    # Even the honesty surface is bounded: the overflow becomes one counter, never a list.
    kept = entries[: policy.max_omissions - 1]
    kept.append(
        Stage0CardOmission(
            kind=Stage0CardOmissionKind.OMISSIONS_TRUNCATED,
            count=len(entries) - len(kept),
        )
    )
    return tuple(kept)


#: Preference order when a decision's ``metrics`` exceed the per-gate byte cap: the compiled
#: summary keys the readiness floors are actually scored against (``client_kb_readiness_metrics``
#: plus the Stage-0 interview counters) go in first, so a single fat caller-supplied blob can never
#: push the load-bearing scalars out. Anything else follows in sorted order.
_GATE_SUMMARY_METRIC_KEYS = (
    "coverage_ratio",
    "verified_claims",
    "open_policy_blocks",
    "project_state_statements",
    "routed_statements_this_turn",
    "material_statements_this_turn",
    "available_field_keys",
)


def bounded_gate_evidence(
    metrics: Mapping[str, JsonValue],
    reason_codes: Sequence[str],
    *,
    policy: Stage0CardPolicy = STAGE0_CARD_POLICY_V1,
) -> tuple[dict[str, JsonValue], tuple[str, ...], bool]:
    """Bound one gate's ``metrics`` + ``reason_codes`` to ``max_gate_evidence_bytes``.

    Deterministic and greedy in :data:`_GATE_SUMMARY_METRIC_KEYS` order: an entry that does not fit
    is *skipped*, not a stop, so one oversized metric cannot hide every smaller one behind it. The
    caller marks the gate ``evidence_truncated`` whenever anything was left out — the full row
    stays reachable through the readiness-history cursor.

    Public because the PC-C8 §7 ``inspect_readiness_history`` tool bounds a *paged ledger row* the
    same way the card bounds a *current-gate* row. Prompt bloat must not simply migrate from the
    opening context into a tool result, and two independent notions of "a bounded readiness row"
    is exactly how the two surfaces would start disagreeing about what was truncated.
    """

    ordered = [key for key in _GATE_SUMMARY_METRIC_KEYS if key in metrics]
    ordered += sorted(set(metrics) - set(_GATE_SUMMARY_METRIC_KEYS))
    kept: dict[str, JsonValue] = {}
    kept_reasons: list[str] = []
    truncated = False

    def fits(candidate_metrics: dict[str, JsonValue], candidate_reasons: list[str]) -> bool:
        payload = {"metrics": candidate_metrics, "reason_codes": candidate_reasons}
        return len(_canonical_json(payload)) <= policy.max_gate_evidence_bytes

    for key in ordered:
        candidate = {**kept, key: metrics[key]}
        if fits(candidate, kept_reasons):
            kept = candidate
        else:
            truncated = True
    for code in reason_codes:
        candidate_reasons = [*kept_reasons, code]
        if fits(kept, candidate_reasons):
            kept_reasons = candidate_reasons
        else:
            truncated = True
    return kept, tuple(kept_reasons), truncated


def _lineage_is_current(
    row: ReadinessDecisionRow,
    *,
    client_kb_version: int,
    product_id: str | None,
    spec_version: int | None,
    confirmed_icps: Sequence[Stage0CardIcpRef],
) -> bool:
    """Whether a decision was taken against the project's *currently pinned* lineage.

    A decision from a superseded lineage is not shown as a verdict — it is history, reachable
    through the bounded readiness-history tool. With no ICP confirmed yet, a decision that pinned
    no ICP is current; once an ICP is confirmed, only decisions pinning a confirmed ``(key,
    version)`` are.
    """

    if row.client_kb_version != client_kb_version or row.product_id != product_id:
        return False
    if spec_version is not None and row.spec_version != spec_version:
        return False
    if confirmed_icps:
        return any(
            row.icp_key == ref.icp_key and row.icp_version == ref.version for ref in confirmed_icps
        )
    return row.icp_key is None and row.icp_version is None


async def _read_project(
    conn: AsyncConnection, *, project_id: str, workspace_id: str
) -> dict[str, str | None]:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT project_id, workspace_id, brand_id, product_id, name "
                    "FROM project WHERE project_id = :project_id"
                ),
                {"project_id": project_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["workspace_id"] != workspace_id:
        # Fail closed: a card is never compiled for a project this workspace does not own.
        raise ValueError("Stage-0 project does not exist in this workspace")
    return dict(row)


async def _read_product_name(
    conn: AsyncConnection, *, product_id: str | None, workspace_id: str
) -> str | None:
    if product_id is None:
        return None
    return (
        await conn.execute(
            text(
                "SELECT name FROM product "
                "WHERE product_id = :product_id AND workspace_id = :workspace_id"
            ),
            {"product_id": product_id, "workspace_id": workspace_id},
        )
    ).scalar_one_or_none()


async def _read_confirmed_icps(
    conn: AsyncConnection, *, workspace_id: str, product_id: str | None
) -> tuple[Stage0CardIcpRef, ...]:
    """The workspace's active ICP specs that belong to this project's product.

    A spec pinned to another product is not this project's ICP; a spec with no product pin is
    workspace-wide and is included.
    """

    rows = (
        (
            await conn.execute(
                text(
                    "SELECT icp_key, version FROM icp_spec "
                    "WHERE workspace_id = :workspace_id AND status = 'active' "
                    "AND (product_id IS NULL OR product_id = :product_id) "
                    "ORDER BY icp_key, version"
                ),
                {"workspace_id": workspace_id, "product_id": product_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(
        Stage0CardIcpRef(icp_key=row["icp_key"], version=int(row["version"])) for row in rows
    )


async def _current_spec_version(conn: AsyncConnection, *, workspace_id: str) -> int | None:
    """The workspace's newest readiness-spec revision — the policy a decision must have used."""

    version = (
        await conn.execute(
            text(
                "SELECT max(version) FROM readiness_spec_revision "
                "WHERE workspace_id = :workspace_id"
            ),
            {"workspace_id": workspace_id},
        )
    ).scalar_one_or_none()
    return int(version) if version is not None else None


def _gate_readiness(
    ledger: Sequence[ReadinessDecisionRow],
    overrides: dict[str, str],
    *,
    client_kb_version: int,
    product_id: str | None,
    spec_version: int | None,
    confirmed_icps: Sequence[Stage0CardIcpRef],
    policy: Stage0CardPolicy,
) -> tuple[Stage0CardGateReadiness, ...]:
    """Latest authoritative, lineage-current decision per gate — override-applied, evidence bounded.

    "Authoritative" means ``created_by_actor='system'``: an agent-authored row is evidence about
    the agent, not a machine verdict. A gate that has history but no lineage-current authoritative
    decision reports :data:`NOT_EVALUATED_FOR_CURRENT_LINEAGE` rather than a stale verdict; a gate
    with no history at all is simply absent.

    Each shown decision's ``metrics``/``reason_codes`` are bounded here — *before* the whole-card
    fit loop — so unbounded caller-supplied readiness evidence can never shed the statements
    instead of itself.
    """

    gates = [gate for gate in ReadinessGate if any(row.gate is gate for row in ledger)]
    entries: list[Stage0CardGateReadiness] = []
    for gate in gates:
        current = [
            row
            for row in ledger
            if row.gate is gate
            and row.created_by_actor == "system"
            and _lineage_is_current(
                row,
                client_kb_version=client_kb_version,
                product_id=product_id,
                spec_version=spec_version,
                confirmed_icps=confirmed_icps,
            )
        ]
        if not current:
            entries.append(
                Stage0CardGateReadiness(
                    gate=gate.value,
                    verdict=NOT_EVALUATED_FOR_CURRENT_LINEAGE,
                    effective_verdict=NOT_EVALUATED_FOR_CURRENT_LINEAGE,
                    decision_lineage=Stage0CardDecisionLineage(
                        client_kb_version=client_kb_version,
                        product_id=product_id,
                        spec_version=spec_version,
                    ),
                )
            )
            continue
        # ``ledger`` is ordered (created_at, id), so the last match is the latest — deterministic
        # even when two decisions share a timestamp.
        latest = current[-1]
        override_ref = overrides.get(str(latest.id))
        metrics, reason_codes, evidence_truncated = bounded_gate_evidence(
            latest.metrics, latest.reason_codes, policy=policy
        )
        entries.append(
            Stage0CardGateReadiness(
                gate=gate.value,
                decision_id=str(latest.id),
                verdict=latest.verdict.value,
                effective_verdict=effective_readiness_verdict(
                    latest.verdict.value, override_ref=override_ref
                ),
                override_ref=override_ref,
                decision_lineage=Stage0CardDecisionLineage(
                    client_kb_version=latest.client_kb_version,
                    product_id=latest.product_id,
                    icp_key=latest.icp_key,
                    icp_version=latest.icp_version,
                    spec_version=latest.spec_version,
                ),
                metrics=metrics,
                reason_codes=reason_codes,
                evidence_truncated=evidence_truncated,
            )
        )
    return tuple(entries)


def _resolved_quotes(
    resolutions: Iterable[ResolvedQuote | ExcludedEvidence],
) -> tuple[dict[str, str], tuple[ExcludedEvidence, ...]]:
    quotes: dict[str, str] = {}
    excluded: list[ExcludedEvidence] = []
    for item in resolutions:
        if isinstance(item, ExcludedEvidence):
            excluded.append(item)
        else:
            quotes[str(item.statement_id)] = item.quote
    return quotes, tuple(excluded)


async def compile_stage0_project_card(
    *,
    project_id: str,
    workspace_id: str,
    client_entity_id: EntityId,
    client_kb_version: int,
    evidence: StatementEvidenceReader,
    product_id: str | None = None,
    proposals_pending: bool = False,
    proposals_stale: bool = False,
    readiness_spec_version: int | None = None,
    policy: Stage0CardPolicy = STAGE0_CARD_POLICY_V1,
    conn_factory: ConnFactory = transaction,
) -> Stage0ProjectCard:
    """Compile the hard-bounded L3 project card from durable Stage-0 state.

    Reads only; the card is a projection, never a write. Everything it shows is either durable
    truth or a count of what the size policy left out — an omission is surfaced, never silent.

    ``product_id`` is the *candidate* product the Client-KB read is scoped to (Stage 0 profiles a
    product before the human confirms it). The card's ``product.confirmed`` reflects the project
    row, not this argument.

    ``proposals_pending`` / ``proposals_stale`` are **caller-supplied**: unconfirmed ICP proposals
    live in a trial-local ``.context`` file today (``stage0_trial._read_icp_proposals``), which is
    not a legal projection source. Only the adapter that owns that file knows the answer, so it
    passes the two booleans in; the card carries no proposal bodies either way (spec §5.1). When a
    future slice persists proposals durably, this reads them here instead and the parameters go.

    ``readiness_spec_version`` pins which readiness-spec revision counts as current; ``None``
    resolves to the workspace's latest revision.
    """

    async with conn_factory() as conn:
        project = await _read_project(conn, project_id=project_id, workspace_id=workspace_id)
        confirmed_product_id = project["product_id"]
        kb_product_id = product_id if product_id is not None else confirmed_product_id
        product_name = await _read_product_name(
            conn, product_id=confirmed_product_id or kb_product_id, workspace_id=workspace_id
        )
        claims = await read_client_kb_claims(
            conn,
            client_entity_id,
            workspace_id=workspace_id,
            version=client_kb_version,
            product_id=kb_product_id,
        )
        live = await read_statements(conn, workspace_id=workspace_id, project_id=project_id)
        with_superseded = await read_statements(
            conn, workspace_id=workspace_id, project_id=project_id, include_superseded=True
        )
        unmapped = await read_statements(
            conn,
            workspace_id=workspace_id,
            project_id=project_id,
            route_kind=StatementRoute.UNMAPPED,
        )
        ledger = await read_readiness_decisions(
            conn, workspace_id=workspace_id, project_id=project_id
        )
        overrides = await readiness_override_refs(
            conn, workspace_id=workspace_id, decision_ids=[row.id for row in ledger]
        )
        confirmed_icps = await _read_confirmed_icps(
            conn, workspace_id=workspace_id, product_id=confirmed_product_id
        )
        spec_version = (
            readiness_spec_version
            if readiness_spec_version is not None
            else await _current_spec_version(conn, workspace_id=workspace_id)
        )

    # Deliberately outside the read transaction above: resolving quotes needs artifact bytes, which
    # the projection layer cannot reach. The seam is therefore a second, later read — and it errs
    # safe: an erasure landing in between makes the statement resolve to ExcludedEvidence, so the
    # card omits words that no longer exist rather than serving a stale copy of them.
    resolutions = await evidence.resolve_quotes(workspace_id=workspace_id, statements=live)
    quotes, excluded = _resolved_quotes(resolutions)
    resolved_rows = [row for row in live if str(row.id) in quotes]
    candidates = _dedup_statements(resolved_rows, quotes)
    deduped_count = len(resolved_rows) - len(candidates)

    readiness = Stage0CardReadiness(
        latest_by_gate=_gate_readiness(
            ledger,
            overrides,
            client_kb_version=client_kb_version,
            product_id=confirmed_product_id,
            spec_version=spec_version,
            confirmed_icps=confirmed_icps,
            policy=policy,
        ),
        ledger_length=len(ledger),
    )
    shown_decisions = tuple(
        entry.decision_id for entry in readiness.latest_by_gate if entry.decision_id is not None
    )

    card_project = Stage0CardProject(
        project_id=str(project["project_id"]),
        name=str(project["name"]),
        workspace_id=workspace_id,
        brand_id=str(project["brand_id"]),
        # The same id the Client-KB read above is scoped to, so the card cannot show the model an
        # entity its own claims section was not compiled against.
        client_entity_id=str(client_entity_id),
    )
    card_product = Stage0CardProduct(
        product_id=confirmed_product_id or kb_product_id,
        name=product_name,
        confirmed=confirmed_product_id is not None,
    )
    card_icp = Stage0CardIcp(
        confirmed=confirmed_icps,
        proposals_pending=proposals_pending,
        proposals_stale=proposals_stale,
    )

    # The per-dimension caps above do not by themselves bound the *serialized* card (each entry
    # carries envelope bytes as well as its quote), so the fit is closed by construction: shed the
    # oldest included statement, then the last Client-KB field, until the canonical bytes fit. Each
    # reduction is re-counted into `omissions`, so the card stays honest about what it dropped.
    statement_limit = policy.max_statements
    kb_limit = len(CLIENT_KNOWLEDGE_FIELDS)
    while True:
        entries = _select_statements(candidates, quotes, policy=policy, limit=statement_limit)
        known_fields, open_gaps = _known_fields(claims, policy=policy, limit=kb_limit)
        statement_cursor = _statement_cursor(entries) if len(entries) < len(candidates) else None
        omissions = _card_omissions(
            policy=policy,
            statements_dropped=len(candidates) - len(entries),
            statement_cursor=statement_cursor,
            evidence_excluded=len(excluded),
            readiness_history=len(ledger) - len(shown_decisions),
            client_knowledge_withheld=(
                sum(1 for key in CLIENT_KNOWLEDGE_FIELDS if key in claims) - len(known_fields)
            ),
            client_kb_version=client_kb_version,
        )
        card = Stage0ProjectCard(
            compiler_policy_version=policy.version,
            project=card_project,
            product=card_product,
            registered_client_claim_fields=tuple(CLIENT_KNOWLEDGE_FIELDS),
            client_knowledge=Stage0CardClientKnowledge(
                version=client_kb_version,
                known_fields=known_fields,
                open_gaps=open_gaps,
            ),
            interview=Stage0CardInterview(
                current_effective_statements=entries,
                selection=Stage0CardSelection(
                    included=len(entries),
                    total_effective=len(candidates),
                    deduped_count=deduped_count,
                    cursor=statement_cursor,
                ),
                unmapped_count=len(unmapped),
                superseded_count=len(with_superseded) - len(live),
            ),
            readiness=readiness,
            icp=card_icp,
            omissions=omissions,
            compiled_from=Stage0CardLineage(
                client_kb_version=client_kb_version,
                statement_selection_digest=_statement_digest(entries),
                readiness_decision_ids=shown_decisions,
                confirmed_icps=confirmed_icps,
                compiler_policy_version=policy.version,
            ),
        )
        size = len(card.canonical_bytes())
        if size <= policy.max_card_bytes:
            return card
        if entries:
            statement_limit = len(entries) - 1
        elif known_fields:
            kb_limit = len(known_fields) - 1
        else:
            raise Stage0CardTooLarge(
                f"Stage-0 project card is {size} bytes with nothing left to drop "
                f"(cap {policy.max_card_bytes}); the fixed sections alone exceed the policy"
            )


__all__ = [
    "NOT_EVALUATED_FOR_CURRENT_LINEAGE",
    "STAGE0_CARD_KIND",
    "STAGE0_CARD_POLICY_V1",
    "STAGE0_CARD_SCHEMA_VERSION",
    "STAGE0_PROJECT_CARD_MEDIA_TYPE",
    "STATEMENT_SELECTION_ORDER",
    "ExcludedEvidence",
    "ExcludedEvidenceReason",
    "ReconBriefView",
    "ResolvedQuote",
    "Stage0CardClientKnowledge",
    "Stage0CardDecisionLineage",
    "Stage0CardGateReadiness",
    "Stage0CardIcp",
    "Stage0CardIcpRef",
    "Stage0CardInterview",
    "Stage0CardKnownField",
    "Stage0CardLineage",
    "Stage0CardOmission",
    "Stage0CardOmissionKind",
    "Stage0CardPolicy",
    "Stage0CardProduct",
    "Stage0CardProject",
    "Stage0CardReadiness",
    "Stage0CardSelection",
    "Stage0CardStatement",
    "Stage0CardTooLarge",
    "Stage0ProgressView",
    "Stage0ProjectCard",
    "Stage0ReadinessView",
    "StatementEvidenceReader",
    "bounded_gate_evidence",
    "compile_stage0_project_card",
    "decode_card_cursor",
    "effective_readiness_verdict",
    "encode_card_cursor",
    "readiness_override_refs",
    "recon_brief",
    "stage0_progress",
    "stage0_readiness",
]
