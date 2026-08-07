"""Import entry scenario — bulk identity resolution + ICP back-scoring + non-fit flagging (M5.3).

Accounts enter the subsystem two ways, **first-class and symmetric** (Doc B §4).
:func:`import_accounts` owns the import sub-pipeline and converges its output into the same
Pass A → tiering → checkpoint → Pass B path discovered accounts take. It does four things and
**re-implements none of them**:

1. **Bulk identity resolution** — every messy free-text row goes through the M2 identity service
   (``identity.resolve_many`` → ``identity.disposition``): a deterministic strong-key hit
   auto-merges (≥0.95, only a domain/registry match ever reaches it — fuzzy caps at 0.85, so two
   same-name companies are **never silently merged**); a mid-band match is routed to the **human
   review queue** (``needs_review``); a no-match parseable row is admitted as a fresh ``candidate``
   ``account_entity`` (``resolved``); a row with no usable identity is surfaced in ``unresolved``
   **with a reason** — never silently dropped (the three Doc B §4.1 failure classes, all explicit).
2. **CRM-aware enrichment** (opt-in) — pulls the client's CRM relationship (and any rubric scoring
   field with a ``crm`` tier) as **tier-1 claims** through the M4 ``sources`` waterfall, detecting
   "already a customer / already in pipeline".
3. **ICP back-scoring** — every resolved account is scored against the client's confirmed
   ``ICPSpec`` (M5.2) via the **M3.4 Pass-A scorer** (``icp.score_entity`` — the same primitive M6
   wraps; import skips *discovery*, never *scoring*). The decomposed fit/intent
   :class:`~clue_core.Score` (each component linking the claims behind it) is returned in
   :class:`ImportResult` — the durable ``account.scoring.*`` write is M6.3's at the SCORING phase;
   this is the early import-time preview.
4. **Non-fit flagging (D6 — flag + proceed)** — an account below the ICP-relative fit floor (the
   confirmed rubric's tier cutoff) is **flagged**, never excluded and never auto-re-deriving the
   ICP (re-derive is M5.2's explicit opt-in, surfaced elsewhere).

The ``resolved`` set is the **same ``account_entity``-keyed shape the discovery path emits** (an
admitted ``candidate`` entity + a ``matched_channel='import'`` discovery-provenance claim), so the
scoring bridge and everything downstream cannot tell discovered from imported accounts except by
that provenance flavor. stage0 imports **no sibling milestone** — back-scoring is the importable
M3.4 ``icp`` service (not M6), and the CRM resolver is reached only through the ``sources``
waterfall seam (bound at the api composition root); the convergence into M6 is store-mediated.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ClaimId,
    Entity,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    PreSpendGate,
    PreSpendRequest,
    PreSpendVerdict,
    ResearchMode,
    RunId,
    Score,
    SourceGate,
    SourceManifest,
    UseClass,
    account_claim,
    contact_claim,
    discovery_claim,
)
from clue_obs.otel import ATTR_WORKSPACE_ID, traced_step
from clue_research.claimstore import (
    WorkspaceScope,
    current_value,
    get_field,
    insert_claim,
    load_core_pack,
    record_run_lineage,
)
from clue_research.icp import (
    ScoringRubric,
    TierCutoffs,
    fit_floor,
    get_rubric_version,
    score_entity,
)
from clue_research.identity import (
    DEFAULT_DISPOSITION_POLICY,
    DEFAULT_REUSE_POLICY,
    DispositionOutcome,
    DispositionPolicy,
    Observation,
    ResolutionMethod,
    ResolutionResult,
    canonical_registry_id,
    disposition,
    embed_account,
    insert_contact_entity,
    registrable_domain,
    resolve,
    resolve_many,
    stamp_reuse,
    surviving_id,
)
from clue_research.stage0.icp_types import ICPSpecRef
from clue_research.stage0.import_fields import (
    CONTACT_IMPORT_RECORD,
    DISCOVERY_PROVENANCE,
    IMPORT_BATCH,
    load_import_pack,
)
from clue_research.stage0.import_types import (
    FitFlag,
    ImportContactResult,
    ImportContactRow,
    ImportResult,
    ImportRow,
    NeedsReviewRow,
    ResolvedAccount,
    UnresolvedRow,
)
from clue_research.stage0.reuse import IMPORT_REUSE_POLICY

_MODE_DISCOVERY = ResearchMode.ACCOUNT_DISCOVERY  # import provenance rides the discovery flavor
_MODE_PROFILING = ResearchMode.ACCOUNT_PROFILING  # CRM enrichment / marker writes
_CRM_RELATIONSHIP_FIELD = "account.crm_relationship_status"
_CUSTOMER_RELATIONSHIPS = frozenset({"customer", "former_customer"})
# Lawful basis recorded on the imported-contact claim (Doc D §4). Professional/non-sensitive B2B
# contact data rests on legitimate interest; sensitive (special-category) data has no outreach
# basis.
_LAWFUL_BASIS_BY_USE_CLASS = {
    UseClass.PROFESSIONAL_PUBLIC: "legitimate_interest",
    UseClass.PERSONAL_PUBLIC_NON_SENSITIVE: "legitimate_interest",
    UseClass.SENSITIVE: "none",
}


def import_batch_run_id(import_batch_id: str) -> RunId:
    """The deterministic run id for an import batch — a retried import with the same
    ``import_batch_id`` re-resolves to the now-existing entities (no duplicate accounts) and the CRM
    waterfall dedups its writes on ``(entity, field, source, run_id)`` rather than double-spend."""
    return RunId(uuid5(NAMESPACE_URL, f"import:{import_batch_id}"))


async def import_accounts(
    conn: AsyncConnection,
    rows: Sequence[ImportRow],
    icp_spec_ref: ICPSpecRef,
    *,
    workspace_id: str,
    client_entity_id: EntityId,
    import_batch_id: str | None = None,
    project_id: str | None = None,
    crm_enrich: bool = False,
    decided_by: str = "auto",
    disposition_policy: DispositionPolicy = DEFAULT_DISPOSITION_POLICY,
    pre_spend_gate: PreSpendGate | None = None,
) -> ImportResult:
    """Bulk-resolve ``rows`` to canonical accounts, back-score them against the confirmed
    ``ICPSpec`` referenced by ``icp_spec_ref``, and return the resolved / needs-review / unresolved
    partition.

    Every input row lands in exactly one outcome (the no-silent-drop invariant). ``crm_enrich``
    pulls the client's CRM relationship as a tier-1 claim and detects "already a customer" (needs a
    ``crm`` resolver bound into the ``sources`` registry at the api root). Run inside a transaction:
    resolution admits/merges entities and writes provenance + marker claims that commit together.
    Each row's full admit + write phase is wrapped in its own ``begin_nested`` savepoint (and each
    contact in a further nested one), so a poison row rolls back only its own writes and surfaces in
    ``unresolved[]`` — one bad row never aborts the batch.

    ``project_id`` attributes the batch's run to a project in ``run_lineage`` (FI-2 P2). Import has
    no project context of its own yet — the caller supplies it; ``None`` registers the batch as a
    workspace-level run, which is the honest state until the import surface threads a project."""
    batch_id = import_batch_id or f"imp-{uuid4().hex[:12]}"
    run_id = import_batch_run_id(batch_id)
    scope = WorkspaceScope.for_workspace(workspace_id)

    with traced_step("stage0.import_accounts", **{ATTR_WORKSPACE_ID: workspace_id}):
        # account.scoring.* / account.crm_relationship_status (core) + import.* /
        # contact.import_record must exist before any claim is written (insert_claim validates it).
        await load_core_pack(conn)
        await load_import_pack(conn)

        # FI-2 P2 (spec §3): register the batch's run once, in the caller's transaction — the same
        # one every provenance/marker claim below commits in. Idempotent, so a retried import with
        # the same ``import_batch_id`` (which re-derives the same run id) re-registers harmlessly.
        await record_run_lineage(
            conn,
            run_id=run_id,
            workspace_id=workspace_id,
            kind="import",
            project_id=project_id,
        )

        rubric = await get_rubric_version(
            conn, icp_spec_ref.workspace_id, icp_spec_ref.icp_key, icp_spec_ref.icp_version
        )

        resolvable: list[ImportRow] = []
        observations: list[Observation] = []
        unresolved: list[UnresolvedRow] = []
        for row in rows:
            if _has_identity(row):
                resolvable.append(row)
                observations.append(_observation(row))
            else:
                unresolved.append(
                    UnresolvedRow(
                        row_index=row.row_index,
                        reason="row carries no usable identity (name, domain, or registry id)",
                        identity_repr=_identity_repr(row),
                    )
                )

        results = (
            await resolve_many(conn, observations, workspace_id=workspace_id)
            if observations
            else []
        )

        # In-memory strong-key index for intra-batch dedup: ``resolve_many`` resolves every row
        # *before* any disposition admits an entity, so two new rows sharing a domain/registry id
        # would each admit a duplicate; collapse the second onto the first here.
        admitted_by_key: dict[str, EntityId] = {}
        resolved: list[ResolvedAccount] = []
        needs_review: list[NeedsReviewRow] = []
        contacts: list[ImportContactResult] = []

        for row, obs, result in zip(resolvable, observations, results, strict=True):
            strong_key = _strong_key(row)

            if result.method is ResolutionMethod.NONE and strong_key is None:
                unresolved.append(
                    UnresolvedRow(
                        row_index=row.row_index,
                        reason="resolution produced no candidate (unparseable or errored row)",
                        identity_repr=_identity_repr(row),
                    )
                )
                continue

            # The whole per-row admit + write phase is savepoint-isolated: a poison row (a raising
            # CRM resolver, a strong-key collision) rolls back its own writes and surfaces in
            # unresolved[] without aborting the batch (the no-silent-drop invariant holds).
            try:
                async with conn.begin_nested():
                    outcome = await _resolve_row(
                        conn,
                        row=row,
                        obs=obs,
                        result=result,
                        strong_key=strong_key,
                        admitted=admitted_by_key,
                        rubric=rubric,
                        scope=scope,
                        workspace_id=workspace_id,
                        run_id=run_id,
                        batch_id=batch_id,
                        crm_enrich=crm_enrich,
                        decided_by=decided_by,
                        disposition_policy=disposition_policy,
                        pre_spend_gate=pre_spend_gate,
                    )
            except Exception:  # noqa: BLE001 — poison-row isolation; the row is surfaced, not dropped
                unresolved.append(
                    UnresolvedRow(
                        row_index=row.row_index,
                        reason="resolution write failed — row isolated",
                        identity_repr=_identity_repr(row),
                    )
                )
                continue

            # Apply the outcome only after its savepoint committed, so a rolled-back admit never
            # leaves a dangling intra-batch index entry.
            if outcome.review is not None:
                needs_review.append(outcome.review)
            elif outcome.resolved is not None:
                resolved.append(outcome.resolved)
                contacts.extend(outcome.contacts)
                if outcome.new_strong_key is not None:
                    admitted_by_key[outcome.new_strong_key[0]] = outcome.new_strong_key[1]
            elif outcome.unresolved is not None:
                unresolved.append(outcome.unresolved)

        await _write_import_batch_marker(
            conn,
            client_entity_id=client_entity_id,
            workspace_id=workspace_id,
            icp_spec_ref=icp_spec_ref,
            import_batch_id=batch_id,
            run_id=run_id,
            counts=(len(resolved), len(needs_review), len(unresolved)),
        )

    return ImportResult(
        import_batch_id=batch_id,
        resolved=tuple(resolved),
        needs_review=tuple(needs_review),
        unresolved=tuple(unresolved),
        contacts=tuple(contacts),
    )


@dataclass(frozen=True)
class _RowOutcome:
    """Where one resolved row lands — exactly one of resolved / review / unresolved is set. The
    caller applies this *after* the row's savepoint commits, so ``new_strong_key`` (the intra-batch
    dedup entry to record for a freshly-admitted entity) is added only on success."""

    resolved: ResolvedAccount | None = None
    review: NeedsReviewRow | None = None
    unresolved: UnresolvedRow | None = None
    contacts: tuple[ImportContactResult, ...] = ()
    new_strong_key: tuple[str, EntityId] | None = None


async def _resolve_row(
    conn: AsyncConnection,
    *,
    row: ImportRow,
    obs: Observation,
    result: ResolutionResult,
    strong_key: str | None,
    admitted: dict[str, EntityId],
    rubric: ScoringRubric | None,
    scope: WorkspaceScope,
    workspace_id: str,
    run_id: RunId,
    batch_id: str,
    crm_enrich: bool,
    decided_by: str,
    disposition_policy: DispositionPolicy,
    pre_spend_gate: PreSpendGate | None,
) -> _RowOutcome:
    """Resolve one row to its outcome inside the caller's savepoint: dispose it (auto-merge / review
    / new-entity / intra-batch), then for a resolved account write provenance, CRM-enrich (opt-in),
    back-score, and tag contacts. Returns a :class:`_RowOutcome`; a review / no-entity row returns
    early, before any account write is attempted."""
    prior = admitted.get(strong_key) if strong_key is not None else None
    if prior is not None:
        entity_id, method, signal, confidence = (
            prior,
            "intra_batch",
            _identity_signal(strong_key),
            1.0,
        )
        new_key: tuple[str, EntityId] | None = None
    else:
        disp = await disposition(
            conn,
            obs,
            result,
            policy=disposition_policy,
            workspace_id=workspace_id,
            decided_by=decided_by,
        )
        if disp.outcome is DispositionOutcome.ENQUEUED:
            if disp.task_id is None:  # defensive — ENQUEUED always carries a task id
                return _RowOutcome(unresolved=_unresolved(row, "review enqueue produced no task"))
            return _RowOutcome(
                review=NeedsReviewRow(
                    row_index=row.row_index,
                    task_id=disp.task_id,
                    top_score=disp.top_score,
                    candidate_entity_ids=tuple(c.entity_id for c in result.candidates),
                )
            )
        if disp.entity_id is None:  # defensive — AUTO_MERGED / NEW_ENTITY always carry an entity
            return _RowOutcome(
                unresolved=_unresolved(row, f"disposition {disp.outcome.value} produced no entity")
            )
        if disp.outcome is DispositionOutcome.AUTO_MERGED:
            entity_id = disp.entity_id
            method, signal, confidence = (
                "deterministic",
                _identity_signal(strong_key),
                disp.top_score,
            )
            new_key = None
        else:  # NEW_ENTITY — a fresh candidate admitted from the row's own identity
            entity_id = disp.entity_id
            method, signal, confidence = "new_entity", "new_entity", 1.0
            await embed_account(conn, entity_id)  # so later rows/runs resolve to it
            new_key = (strong_key, entity_id) if strong_key is not None else None

    entity_id = await surviving_id(conn, entity_id, EntityType.ACCOUNT)
    provenance_id = await _write_resolution_provenance(
        conn,
        entity_id=entity_id,
        row=row,
        run_id=run_id,
        workspace_id=workspace_id,
        method=method,
        matched_signal=signal,
        confidence=confidence,
    )

    crm_relationship: str | None = None
    already_customer = False
    if crm_enrich:
        crm_relationship = await _crm_enrich(
            conn,
            entity_id=entity_id,
            rubric=rubric,
            scope=scope,
            workspace_id=workspace_id,
            run_id=run_id,
            pre_spend_gate=pre_spend_gate,
        )
        already_customer = crm_relationship in _CUSTOMER_RELATIONSHIPS

    fit, intent, flag = await _back_score(conn, entity_id=entity_id, rubric=rubric, scope=scope)

    row_contacts: list[ImportContactResult] = []
    for contact in row.contacts:
        # A poison contact (e.g. a strong-key collision) is isolated in its own nested savepoint and
        # skipped — the resolved account stands (flag + proceed; never abort the row).
        try:
            async with conn.begin_nested():
                cres = await _resolve_and_tag_contact(
                    conn,
                    contact=contact,
                    account_id=entity_id,
                    row_index=row.row_index,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    import_batch_id=batch_id,
                    jurisdiction=_row_jurisdiction(row),
                )
                if cres is not None:
                    row_contacts.append(cres)
        except Exception:  # noqa: BLE001 — poison-contact isolation, the resolve_many discipline
            continue

    resolved = ResolvedAccount(
        account_entity_id=entity_id,
        row_index=row.row_index,
        fit_score=fit,
        intent_score=intent,
        fit_flag=flag,
        already_customer=already_customer,
        crm_relationship=crm_relationship,
        resolution_method=method,
        matched_signal=signal,
        resolution_confidence=confidence,
        provenance_claim_id=provenance_id,
    )
    return _RowOutcome(resolved=resolved, contacts=tuple(row_contacts), new_strong_key=new_key)


def _unresolved(row: ImportRow, reason: str) -> UnresolvedRow:
    return UnresolvedRow(row_index=row.row_index, reason=reason, identity_repr=_identity_repr(row))


# --- row → observation / identity helpers ----------------------------------


def _has_identity(row: ImportRow) -> bool:
    return bool(row.name or row.domain or row.registry_ids)


def _observation(row: ImportRow) -> Observation:
    return Observation(
        name=row.name or "",
        entity_type=EntityType.ACCOUNT,
        domain=row.domain,
        registry_ids=row.registry_ids,
        geo=row.geo,
        aliases=row.aliases,
    )


def _strong_key(row: ImportRow) -> str | None:
    """A deterministic dedup key (registrable domain, else the first registry id) or ``None`` when
    the row has only a fuzzy name — matching the strong keys M2 auto-merges on. The registry id is
    canonicalized exactly as the M2 DB paths do (``canonical_registry_id``), so two textual variants
    of the same id (``{"duns": "12-345"}`` / ``{"DUNS": "123 45"}``) produce the *same* key and the
    intra-batch index collapses them — else the second row would mint a duplicate entity (or hit the
    registry unique index and abort the row)."""
    if row.domain:
        rd = registrable_domain(row.domain)
        if rd:
            return f"domain:{rd}"
    if row.registry_ids:
        canon = sorted(
            (ns, val)
            for ns, val in (canonical_registry_id(k, v) for k, v in row.registry_ids.items())
            if val
        )
        if canon:
            ns, val = canon[0]
            return f"registry:{ns}:{val}"
    return None


def _identity_signal(strong_key: str | None) -> str:
    """The *kind* of the strong key (``domain`` / ``registry`` / ``name+geo``), derived from the key
    itself so it can never drift from :func:`_strong_key`'s priority ladder."""
    return strong_key.split(":", 1)[0] if strong_key else "name+geo"


def _identity_repr(row: ImportRow) -> str:
    if row.name:
        return row.name
    if row.domain:
        return row.domain
    if row.registry_ids:
        return next(iter(row.registry_ids.values()))
    return ""


def _row_jurisdiction(row: ImportRow) -> str | None:
    if not row.geo:
        return None
    val = row.geo.get("jurisdiction") or row.geo.get("country")
    return str(val) if val else None


# --- resolution provenance (the convergence + audit artifact) --------------


async def _write_resolution_provenance(
    conn: AsyncConnection,
    *,
    entity_id: EntityId,
    row: ImportRow,
    run_id: RunId,
    workspace_id: str,
    method: str,
    matched_signal: str,
    confidence: float,
) -> ClaimId:
    """Write the per-row resolution provenance as a discovery-flavored claim
    (``matched_channel='import'``) — the convergence contract M6 reads (an admitted ``candidate`` +
    its discovery-provenance claim), and the audit trail the client inspects (which row resolved to
    which entity, by which key, at what confidence). ``insert_claim`` skips the field-registry check
    for discovery claims, and the discovery envelope forces ``research_mode=account_discovery``;
    ``found_via='import:row#N'`` keeps it distinguishable from a discovered account.

    Stamped **tenant-private**: the account entity is cross-tenant-shared, but *which accounts this
    client imported* (and at which row) is client-tuned, competitively-sensitive signal — the same
    class as ``account.scoring.*`` and ``crm_import`` relationships. Symmetry with discovery is a
    matter of output *shape*, not tenancy. M6 reads it under the importing client's own scope, and
    discovery claims are excluded from field merges regardless of scope, so convergence holds."""
    claim = discovery_claim(
        entity_id=entity_id,
        entity_type=EntityType.ACCOUNT,
        field_key=DISCOVERY_PROVENANCE,
        value_json={
            "matched_channel": "import",
            "row_index": row.row_index,
            "resolution_method": method,
            "matched_signal": matched_signal,
        },
        source_tier=1,
        extraction_method=ExtractionMethod.HUMAN,  # the client supplied the list
        confidence=confidence,
        run_id=run_id,
        research_mode=_MODE_DISCOVERY,
        found_via=f"import:row#{row.row_index}",
        matched_signal=matched_signal,
        discovery_confidence=confidence,
        evidence_span=f"client import row {row.row_index}",
    )
    claim = stamp_reuse(claim, workspace_id=workspace_id, policy=IMPORT_REUSE_POLICY)
    return await insert_claim(conn, claim)


# --- CRM tier-1 enrichment ("already a customer") --------------------------


async def _crm_enrich(
    conn: AsyncConnection,
    *,
    entity_id: EntityId,
    rubric: ScoringRubric | None,
    scope: WorkspaceScope,
    workspace_id: str,
    run_id: RunId,
    pre_spend_gate: PreSpendGate | None,
) -> str | None:
    """Resolve every ``crm``-tier field (the CRM relationship plus any rubric scoring field whose
    tier plan starts at ``crm``) through the M4 waterfall, writing tier-1 ``crm_import`` claims,
    then return the client-CRM relationship value (``customer`` / ``open_opportunity`` / …) for the
    "already a customer / already in pipeline" signal. A field with no ``crm`` resolver bound simply
    no-ops (the waterfall stops at ``NO_RESOLVER``)."""
    from clue_research.sources import resolve_field  # lazy: keep the import seam narrow

    def gate_for(field_key: str) -> SourceGate:
        async def source_gate(manifest: SourceManifest) -> bool:
            if pre_spend_gate is None:
                return True
            decision = await pre_spend_gate.check(
                PreSpendRequest(
                    entity_id=entity_id,
                    entity_type=EntityType.ACCOUNT,
                    field_key=field_key,
                    source_tier=manifest.tier,
                    source_key=manifest.source_key,
                    run_id=run_id,
                )
            )
            return decision.verdict is PreSpendVerdict.PASS

        return source_gate

    field_keys = {_CRM_RELATIONSHIP_FIELD}
    if rubric is not None:
        field_keys.update(rubric.field_keys)

    entity = Entity(entity_id=entity_id, entity_type=EntityType.ACCOUNT)
    for field_key in sorted(field_keys):
        field_def = await get_field(conn, field_key)
        if field_def is None or "crm" not in field_def.tier_plan:
            continue
        await resolve_field(
            conn,
            entity,
            field_def,
            mode=_MODE_PROFILING,
            run_id=run_id,
            workspace_id=workspace_id,
            reuse_policy=DEFAULT_REUSE_POLICY,  # crm_import → tenant_private via default methods
            source_gate=gate_for(field_key),
        )

    cv = await current_value(conn, entity_id, _CRM_RELATIONSHIP_FIELD, scope=scope)
    if cv is None or not isinstance(cv.value_json, str):
        return None
    return cv.value_json


# --- ICP back-scoring + non-fit flagging (D6) ------------------------------


async def _back_score(
    conn: AsyncConnection,
    *,
    entity_id: EntityId,
    rubric: ScoringRubric | None,
    scope: WorkspaceScope,
) -> tuple[Score, Score, FitFlag]:
    """Back-score one resolved account against the confirmed rubric via the M3.4 Pass-A scorer and
    derive its D6 fit flag. With no confirmed rubric there is no ICP fit criterion, so the scores
    are empty and the account is not flagged (an honest no-op)."""
    if rubric is None:
        empty = Score(value=0.0)
        return empty, empty, FitFlag.FIT
    result = await score_entity(conn, rubric, entity_id, scope=scope)
    return (
        result.as_fit_score(),
        result.as_intent_score(),
        _fit_flag(result.fit_score, rubric.tier_cutoffs),
    )


def _fit_flag(fit_score: float, cutoffs: TierCutoffs) -> FitFlag:
    """Flag an account ``NON_FIT`` when its fit falls below the ICP-relative fit floor (the M3.4
    :func:`~clue_research.icp.fit_floor` — the lowest ``min_fit`` across the rubric's tier bands;
    the *same* threshold M5.4 lookalike seeding gates on, single-sourced there). A rubric that sets
    no fit floor (``0.0``) flags nothing (the client set no bar)."""
    floor = fit_floor(cutoffs)
    return FitFlag.NON_FIT if floor > 0.0 and fit_score < floor else FitFlag.FIT


# --- imported contacts (Doc D §2/§4 governance tagging) --------------------


async def _resolve_and_tag_contact(
    conn: AsyncConnection,
    *,
    contact: ImportContactRow,
    account_id: EntityId,
    row_index: int,
    workspace_id: str,
    run_id: RunId,
    import_batch_id: str,
    jurisdiction: str | None,
) -> ImportContactResult | None:
    """Resolve/admit one imported contact under its account and write a governed
    ``contact.import_record`` claim. The claim carries the Doc D §2 ``identity_binding`` (``strong``
    when a verified email/LinkedIn pins the person, else ``weak`` — a weak binding never drives
    outreach) and ``use_class`` tags, plus the recorded lawful basis in its value (Doc D §4), so
    M10's use-gate can govern it later. Contact resolution *depth* (fuzzy, committee roles) is M8;
    here a strong-key contact reuses its entity, otherwise a fresh candidate is admitted."""
    if not (contact.name or contact.email or contact.linkedin_url):
        return None

    binding = (
        IdentityBinding.STRONG if (contact.email or contact.linkedin_url) else IdentityBinding.WEAK
    )
    contact_id = await _resolve_contact_entity(conn, contact, account_id, workspace_id=workspace_id)
    lawful_basis = _LAWFUL_BASIS_BY_USE_CLASS[contact.use_class]

    value_json: dict[str, JsonValue] = {
        "account_entity_id": str(account_id),
        "lawful_basis": lawful_basis,
        "import_batch_id": import_batch_id,
        "row_index": row_index,
    }
    if contact.title:
        value_json["title"] = contact.title
    if contact.email:
        value_json["email"] = contact.email
    if contact.linkedin_url:
        value_json["linkedin_url"] = contact.linkedin_url
    if jurisdiction:
        value_json["jurisdiction"] = jurisdiction
    if lawful_basis == "legitimate_interest":
        value_json["lia_ref"] = "import-default-LIA"

    claim = contact_claim(
        entity_id=contact_id,
        field_key=CONTACT_IMPORT_RECORD,
        value_json=value_json,
        source_tier=1,
        extraction_method=ExtractionMethod.CRM_IMPORT,
        confidence=1.0,
        run_id=run_id,
        research_mode=_MODE_PROFILING,
        identity_binding=binding,
        use_class=contact.use_class,
        evidence_span=f"client import row {row_index} contact",
    )
    claim = stamp_reuse(claim, workspace_id=workspace_id, policy=IMPORT_REUSE_POLICY)
    await insert_claim(conn, claim)

    return ImportContactResult(
        contact_entity_id=contact_id,
        account_entity_id=account_id,
        row_index=row_index,
        identity_binding=binding.value,
        use_class=contact.use_class.value,
        lawful_basis=lawful_basis,
    )


async def _resolve_contact_entity(
    conn: AsyncConnection, contact: ImportContactRow, account_id: EntityId, *, workspace_id: str
) -> EntityId:
    if contact.email or contact.linkedin_url:
        result = await resolve(
            conn,
            Observation(
                name=contact.name or "",
                entity_type=EntityType.CONTACT,
                verified_email=contact.email,
                linkedin_url=contact.linkedin_url,
            ),
            workspace_id=workspace_id,
        )
        if result.top is not None and result.top_score >= 1.0:
            return await surviving_id(conn, result.top.entity_id, EntityType.CONTACT)
    return await insert_contact_entity(
        conn,
        account_entity_id=account_id,
        full_name=contact.name,
        verified_email=contact.email,
        linkedin_url=contact.linkedin_url,
    )


# --- the import-batch grouping marker --------------------------------------


async def _write_import_batch_marker(
    conn: AsyncConnection,
    *,
    client_entity_id: EntityId,
    workspace_id: str,
    icp_spec_ref: ICPSpecRef,
    import_batch_id: str,
    run_id: RunId,
    counts: tuple[int, int, int],
) -> ClaimId:
    """Write the ``import.batch`` grouping marker on the client entity (claim-native,
    tenant-private) — one immutable claim per import run recording the ICP ref and the
    resolved/needs-review/unresolved counts, queryable and auditable with the rest of the store."""
    resolved_n, review_n, unresolved_n = counts
    claim = account_claim(
        entity_id=client_entity_id,
        field_key=IMPORT_BATCH,
        value_json={
            "import_batch_id": import_batch_id,
            "icp_key": icp_spec_ref.icp_key,
            "icp_version": icp_spec_ref.icp_version,
            "resolved_count": resolved_n,
            "needs_review_count": review_n,
            "unresolved_count": unresolved_n,
        },
        source_tier=1,
        extraction_method=ExtractionMethod.HUMAN,
        confidence=1.0,
        run_id=run_id,
        research_mode=_MODE_PROFILING,
        evidence_span=f"client import batch {import_batch_id}",
    )
    claim = stamp_reuse(claim, workspace_id=workspace_id, policy=IMPORT_REUSE_POLICY)
    return await insert_claim(conn, claim)
