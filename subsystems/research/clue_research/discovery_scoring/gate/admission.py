"""The admission gate — resolve, admit, and stamp discovery-provenance (M6.2 / ENG-133).

``admit`` is the single seam every discovered (and imported) candidate passes through. It:

1. **Existence-checks** the candidate (pluggable; default = has a resolvable identity). A candidate
   with nothing to resolve to is **rejected** — no ``account_entity``, no claim (anti-fabrication).
2. Builds an :class:`~clue_research.identity.Observation` and calls the **M2 identity service**
   (``resolve`` → ``disposition``): the *only* component allowed to turn a name into an id. Outcomes
   map to ``ADMITTED`` (deterministic/strong auto-merge → an existing entity, or a fresh candidate),
   ``NEEDS_REVIEW`` (mid-band → the M2 review queue, never guessed), or ``REJECTED``.
3. For an admitted entity, writes exactly **one** *discovery-provenance* claim (the staged-flow §9
   flavor) recording where it was found, why it matched, and how confident — idempotently, so an
   M7 phase replay re-admitting the same candidate is a no-op.
4. Records the admitted account's **``project_account`` membership** (FI-2 P1, spec §2) when the
   caller supplies ``project_id`` — in the same transaction as the provenance claim, so "this
   project targets that account" can never disagree with the admission that created it.

Concurrency: two workers admitting the same company must not double-admit. With a Redis client the
gate takes an in-flight lock keyed on the candidate's strong key (its registrable domain) so the
second worker resolves to the first's entity rather than racing an insert; the DB strong-key
unique constraint is the backstop. The gate is channel-agnostic, so an imported, pre-resolved row
(``matched_channel='import'``) converges through the *same* path — one gate, two entry scenarios
(Doc B §4). Admission is account-level existence only — no personal data — so the Doc D gates (M10)
do not apply here (D8).
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    Modality,
    ResearchMode,
    RunId,
    SourceTier,
    discovery_claim,
    revalidate_with,
)
from clue_locks import entity_lock
from clue_research.claimstore import ALL_WORKSPACES, claims_for, insert_claim
from clue_research.discovery_scoring.discovery import CandidateHypothesis
from clue_research.discovery_scoring.gate.existence import (
    DEFAULT_EXISTENCE_CHECK,
    ExistenceCheck,
)
from clue_research.discovery_scoring.gate.results import AdmissionResult, AdmissionStatus
from clue_research.identity import (
    DEFAULT_DISPOSITION_POLICY,
    DEFAULT_EMBEDDER,
    DEFAULT_RESOLUTION_POLICY,
    DispositionOutcome,
    DispositionPolicy,
    Embedder,
    Observation,
    ResolutionPolicy,
    disposition,
    merged_member_ids,
    registrable_domain,
    resolve,
    surviving_id,
)
from clue_research.membership import ensure_project_account
from clue_research.sources import get_source

# The registered field-key the discovery-provenance claim lands on. A discovery-flavored claim skips
# field-registry validation (it is admission evidence, not a typed field value — see
# ``claimstore.insert_claim``), and it never wins a merge, so no registration is required.
DISCOVERY_PROVENANCE_FIELD = "core.discovery_provenance"

# The reserved channel label M5's import pipeline stamps so an imported account converges through
# the same gate and is indistinguishable downstream except by this channel (Doc B §4).
IMPORT_CHANNEL = "import"

_LOCK_PREFIX = "clue:discovery-admit:"


def membership_channel(matched_channel: str) -> str:
    """The default FI-2 ``project_account.added_via`` channel for a ``matched_channel``.

    The gate is deliberately channel-agnostic — an imported row converges through the same path as
    a discovered one (Doc B §4) — but membership is not: the row records *how the account joined
    the project*, and the reserved ``import`` channel is the one entry scenario that is not
    discovery. One rule in one place, so every caller of :func:`admit` records the same thing.

    ``matched_channel`` is the gate's **resolution-path** label, which is not always the join
    provenance: a human typing a domain into a surface resolves through the ``import`` path (it is
    client-supplied, tier-1 data) but joins the project as ``manual``. Such a caller passes
    :func:`admit`'s ``added_via`` explicitly rather than bending its ``matched_channel``, which
    would also change the claim's source tier and extraction method.
    """
    return "imported" if matched_channel == IMPORT_CHANNEL else "discovered"


def _domain_lock_id(workspace_id: str, domain: str) -> EntityId:
    """A deterministic lock id derived from a candidate's ``(workspace, registrable domain)``, so
    two workers admitting the same company *in the same workspace* contend on one Redis lock even
    before either entity exists — while two workspaces admitting the same domain never serialize on
    each other. Accounts are workspace-local ([B3×research]) and the DB strong-key uniqueness is
    likewise ``(workspace_id, domain)``; a domain-only lock would serialize tenants needlessly."""
    return EntityId(uuid5(NAMESPACE_URL, f"{_LOCK_PREFIX}{workspace_id}:{domain}"))


def _to_observation(candidate: CandidateHypothesis) -> Observation:
    """Build the identity-service :class:`Observation` from a candidate. The strong key is the
    candidate's *own* registrable domain (never ``source_url``, which may be a platform host); the
    name is the unresolved company name. Resolution folds/normalizes these (M2).

    ``aliases`` carries the candidate's raw name (FI-2 §1.2-H1). A hypothesis has no alias list of
    its own — the one name a channel reported is all there is — but the scorer's ``alias_overlap``
    arm compares the observation's *name-keys* against the candidate entity's stored match-key
    index, so supplying it is what lets an exact normalized-name hit earn that arm. Without it the
    arm is dead weight for every discovered candidate (import supplies its row's aliases here for
    exactly the same reason), and the arm is the difference between "route this to review" and
    "silently mint a duplicate" for a domain-less re-encounter. It is a distinct signal from
    ``name_token_jaccard``: overlap needs the whole folded key to match, not merely tokens."""
    domain = registrable_domain(candidate.candidate_domain) if candidate.candidate_domain else None
    return Observation(
        name=candidate.raw_name or "",
        entity_type=EntityType.ACCOUNT,
        domain=domain,
        geo=candidate.candidate_geo,
        aliases=(candidate.raw_name,) if candidate.raw_name else (),
    )


async def _provenance_origin(
    conn: AsyncConnection, matched_channel: str
) -> tuple[SourceTier, ExtractionMethod]:
    """The ``(source_tier, extraction_method)`` for the provenance claim, per the matching resolver.

    Imports are tier-1 client data (``crm_import``). Otherwise the channel's registered manifest
    supplies the tier + modality (structured → ``api``, else ``scrape``); an unregistered channel
    (e.g. lookalike) falls back to a grounded tier-2 ``scrape`` default. The exact value is
    provenance metadata — a discovery claim never wins a merge — so a default is safe."""
    if matched_channel == IMPORT_CHANNEL:
        return 1, ExtractionMethod.CRM_IMPORT
    manifest = await get_source(conn, matched_channel)
    if manifest is not None:
        method = (
            ExtractionMethod.API
            if manifest.modality is Modality.STRUCTURED
            else ExtractionMethod.SCRAPE
        )
        return manifest.tier, method
    return 2, ExtractionMethod.SCRAPE


async def _existing_provenance(
    conn: AsyncConnection,
    entity_id: EntityId,
    run_id: RunId,
    matched_channel: str,
    artifact_key: str | None,
) -> ClaimId | None:
    """The id of an existing discovery-provenance claim for this ``(entity, run, channel)``, if
    any — the idempotency check that makes re-admission an M7-replay-safe no-op.

    Merge-aware: ``claims_for`` filters strictly on ``entity_id`` and does not resolve across a
    merge, so we check every member of the survivor's merge set (``entity_id`` is already the
    survivor). Otherwise a candidate admitted as a new entity in run 1, then merged into another
    entity before a replay, would have its provenance missed and a duplicate written."""
    for member in await merged_member_ids(conn, entity_id, EntityType.ACCOUNT):
        for claim in await claims_for(
            conn, member, DISCOVERY_PROVENANCE_FIELD, scope=ALL_WORKSPACES
        ):
            provenance = claim.discovery_provenance
            base_match = (
                provenance is not None
                and provenance.run_id == run_id
                and provenance.found_via == matched_channel
            )
            # Durable provider items are independently valuable evidence even when several map to
            # one survivor. Their content-addressed artifact is therefore the replay identity.
            # Legacy channels with no artifact retain the original one-claim-per-run/channel rule.
            if base_match and (
                claim.artifact_key == artifact_key if artifact_key is not None else True
            ):
                return claim.id
    return None


async def ensure_discovery_provenance(
    conn: AsyncConnection,
    candidate: CandidateHypothesis,
    entity_id: EntityId,
    run_id: RunId,
) -> ClaimId:
    """Write (idempotently) the one discovery-provenance claim for an admitted entity."""
    existing = await _existing_provenance(
        conn,
        entity_id,
        run_id,
        candidate.matched_channel,
        candidate.artifact_key,
    )
    if existing is not None:
        return existing
    source_tier, extraction_method = await _provenance_origin(conn, candidate.matched_channel)
    claim = discovery_claim(
        entity_id=entity_id,
        entity_type=EntityType.ACCOUNT,
        field_key=DISCOVERY_PROVENANCE_FIELD,
        value_json={
            "matched_channel": candidate.matched_channel,
            "matched_signal": candidate.matched_signal,
            "discovery_confidence": candidate.resolver_confidence,
            "evidence": candidate.discovery_evidence,
        },
        source_tier=source_tier,
        extraction_method=extraction_method,
        confidence=candidate.resolver_confidence,
        run_id=run_id,
        research_mode=ResearchMode.ACCOUNT_DISCOVERY,
        found_via=candidate.matched_channel,
        matched_signal=candidate.matched_signal,
        discovery_confidence=candidate.resolver_confidence,
        # the candidate's grounding (M6.1 guarantees one of these is non-empty)
        source_url=candidate.source_url or candidate.source_record_ref,
        evidence_span=candidate.evidence_span,
        observed_at=candidate.observed_at,
        cost_cents=candidate.cost_cents,
    )
    claim = revalidate_with(
        claim,
        source_key=candidate.matched_channel,
        artifact_key=candidate.artifact_key,
    )
    return await insert_claim(conn, claim)


async def _admit_resolved(
    conn: AsyncConnection,
    candidate: CandidateHypothesis,
    observation: Observation,
    run_id: RunId,
    *,
    workspace_id: str,
    project_id: str | None,
    added_via: str | None,
    redis: Redis | None,
    resolution_policy: ResolutionPolicy,
    disposition_policy: DispositionPolicy,
    embedder: Embedder,
) -> AdmissionResult:
    """Resolve the observation, route it through the M2 disposition band, and (if admitted) stamp
    the discovery-provenance claim and the project membership. Run under the in-flight lock when
    one is held."""
    result = await resolve(
        conn, observation, policy=resolution_policy, embedder=embedder, workspace_id=workspace_id
    )
    decision = await disposition(
        conn,
        observation,
        result,
        policy=disposition_policy,
        redis=redis,
        workspace_id=workspace_id,
        # FI-2 P1: a mid-band candidate admits nothing, so it cannot join the project here. The
        # project rides the enqueued review task instead, so the human resolution can join the
        # entity it creates or merges into — the admitting project and the membership can then
        # never disagree, because they are the same value.
        project_id=project_id,
        decided_by="discovery",
        # FI-2 §1.2-H1: the gate's own embedder rides through to the new-entity path, so an
        # account this admission mints is embedded in the same transaction that created it. The
        # gate already resolves *against* embeddings; before this it never wrote one, so every
        # discovered account was a permanent ANN blind spot to the next name-only encounter.
        embedder=embedder,
    )
    if decision.outcome is DispositionOutcome.ENQUEUED:
        return AdmissionResult(status=AdmissionStatus.NEEDS_REVIEW, review_task_id=decision.task_id)
    if decision.entity_id is None:  # defensive — AUTO_MERGED/NEW_ENTITY always carry an entity id
        raise RuntimeError(f"disposition {decision.outcome} returned no entity_id")
    entity_id = await surviving_id(conn, decision.entity_id, EntityType.ACCOUNT)
    claim_id = await ensure_discovery_provenance(conn, candidate, entity_id, run_id)
    if project_id is not None:
        # FI-2 P1 (spec §2): the admission *is* the join — record it here, on the survivor, in the
        # admission's own transaction. Idempotent and first-add-wins, so an M7 replay (or a second
        # project admitting the same workspace-global account) never rewrites the original add.
        await ensure_project_account(
            conn,
            workspace_id=workspace_id,
            project_id=project_id,
            account_entity_id=entity_id,
            added_via=added_via or membership_channel(candidate.matched_channel),
        )
    return AdmissionResult(
        status=AdmissionStatus.ADMITTED,
        account_entity_id=entity_id,
        discovery_provenance_claim_id=claim_id,
    )


async def admit(
    conn: AsyncConnection,
    candidate: CandidateHypothesis,
    run_id: RunId,
    *,
    workspace_id: str,
    project_id: str | None = None,
    added_via: str | None = None,
    redis: Redis | None = None,
    existence: ExistenceCheck = DEFAULT_EXISTENCE_CHECK,
    resolution_policy: ResolutionPolicy = DEFAULT_RESOLUTION_POLICY,
    disposition_policy: DispositionPolicy = DEFAULT_DISPOSITION_POLICY,
    embedder: Embedder = DEFAULT_EMBEDDER,
) -> AdmissionResult:
    """Admit one candidate through the existence/identity gate. See the module docstring.

    Returns ``REJECTED`` (no entity, no claim) for a candidate that fails the existence check or has
    nothing to resolve to; ``NEEDS_REVIEW`` (with the M2 ``review_task_id``) for a mid-band match;
    ``ADMITTED`` (with the resolved ``account_entity_id`` + the discovery-provenance claim) else.
    Idempotent: re-admitting the same candidate for the same run reuses the existing provenance
    claim. Pass a ``redis`` client to serialize concurrent same-company admits.

    ``project_id`` is the project this admission is admitting *for*: supplied, the admitted account
    joins that project's target list (``project_account``, FI-2 §2). Left ``None`` the admission is
    workspace-level and records no membership — the account is workspace-global either way (R1), so
    a projectless caller produces a real, usable account with no project claiming it. Only an
    ``ADMITTED`` outcome joins here: a ``NEEDS_REVIEW`` candidate has no entity yet, so the project
    is stamped on the enqueued review task and the human resolution joins the entity it creates or
    merges into (``identity.resolve_merge_into`` / ``resolve_create_new_entity``).

    ``embedder`` is the swappable name-embedding model. It is used **both** to resolve the candidate
    (the ANN arm) and — since FI-2 §1.2-H1 — to embed an account this admission *mints*, in the same
    transaction, so the next name-only encounter of that company can find it. Defaulted, so no
    caller has to supply one; swap it (with the matching ``resolution_policy.model_version``) to
    change the model.

    ``added_via`` overrides the channel the membership records. It defaults to
    :func:`membership_channel` over the candidate's ``matched_channel`` — pass it only when the
    resolution path and the join provenance genuinely differ (a hand-typed account resolves through
    the ``import`` path but joins as ``manual``). An unknown value is refused by
    ``ensure_project_account`` before any statement is issued.
    """
    verdict = await existence.check(candidate)
    if not verdict.exists:
        return AdmissionResult(status=AdmissionStatus.REJECTED, reason=verdict.reason)

    observation = _to_observation(candidate)
    if observation.domain is None and not observation.name.strip():
        return AdmissionResult(
            status=AdmissionStatus.REJECTED, reason="nothing to resolve to (no domain or name)"
        )

    # Serialize concurrent admits of the same company on its strong key (domain). A domain-less
    # (name-only) candidate takes no lock: there is no unique constraint to race on, and fuzzy
    # name dedup / the review queue is the backstop for concurrent name-only admits.
    if redis is not None and observation.domain is not None:
        async with entity_lock(
            redis, EntityType.ACCOUNT, _domain_lock_id(workspace_id, observation.domain)
        ):
            return await _admit_resolved(
                conn,
                candidate,
                observation,
                run_id,
                workspace_id=workspace_id,
                project_id=project_id,
                added_via=added_via,
                redis=redis,
                resolution_policy=resolution_policy,
                disposition_policy=disposition_policy,
                embedder=embedder,
            )
    return await _admit_resolved(
        conn,
        candidate,
        observation,
        run_id,
        workspace_id=workspace_id,
        project_id=project_id,
        added_via=added_via,
        redis=redis,
        resolution_policy=resolution_policy,
        disposition_policy=disposition_policy,
        embedder=embedder,
    )


__all__ = [
    "admit",
    "ensure_discovery_provenance",
    "membership_channel",
    "DISCOVERY_PROVENANCE_FIELD",
    "IMPORT_CHANNEL",
]
