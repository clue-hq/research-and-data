"""Hybrid lookalike seeding — assemble + rank seeds for M6 discovery (M5.4).

Import and discovery are **not exclusive** (Doc B §4 Hybrid): a client's imported list, plus the
existing customers surfaced during reverse-profiling, are the **strongest seeds for lookalike
discovery** — "accounts like yours you may have missed". :func:`assemble_lookalike_seeds` collects,
ranks, and packages those seeds into the :class:`~clue_research.stage0.seeds_types.SeedSet` that
**M6 mode-M1 lookalike expansion** consumes. It **produces the seeds, not the discovery run** (the
expand loop, stopping rule, budget cap, and existence gate are all M6's), and it re-implements no
identity resolution or scoring — it calls the M2 identity service and the M3.4 scorer as services.

Three seed sources, all reduced to **resolved ``account_entity``s** (never free-text — the M2
invariant, conventions §2):

1. **Existing-customer evidence (M5.1)** — the ``client.customer`` list captured during
   reverse-profiling. Each ``{name, domain}`` is resolved through the identity service
   (deterministic / high-confidence reuse), then back-scored against the **target** ICP via the
   M3.4 scorer so the per-ICP partition is honest (a healthcare customer clears the healthcare ICP's
   fit floor, not the fintech ICP's — D5).
2. **CRM existing customers (M5.3)** — resolved imports the import pipeline flagged
   ``already_customer`` (a CRM tier-1 relationship). The strongest anchors.
3. **High-fit imports (M5.3)** — resolved imports above the ICP fit floor. A **non-fit** import is
   **excluded from seeding** (D6 default: a non-fit anchor seeds non-fit lookalikes) while remaining
   in the researched list.

Import back-scores are **in-memory only** (M5.3 does not persist ``account.scoring.*`` — that is
M6.3's durable write), so M5.4 consumes the :class:`~clue_research.stage0.import_types.ImportResult`
directly rather than a persisted batch ref. The hybrid default is research-the-list **and**
discover-lookalikes; the client can opt out (always-has-the-wheel — Doc B §1), which yields a
**suppressed** empty SeedSet that leaves the import-only path intact.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import TenantScope, claims_for, insert_claim
from clue_research.core import (
    AccountStatus,
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    RunId,
    discovery_claim,
)
from clue_research.icp import ScoringRubric, fit_floor, get_rubric_version, score_entity
from clue_research.identity import (
    Observation,
    embed_account,
    insert_account_entity,
    registrable_domain,
    resolve,
    stamp_reuse,
    surviving_id,
)
from clue_research.obs import ATTR_CLIENT_ID, traced_step
from clue_research.stage0.client_kb import read_client_kb_claims
from clue_research.stage0.fields import CLIENT_CUSTOMER
from clue_research.stage0.icp_types import ICPSpecRef, SeedAccount
from clue_research.stage0.import_fields import DISCOVERY_PROVENANCE
from clue_research.stage0.import_types import FitFlag, ImportResult
from clue_research.stage0.reuse import SEED_REUSE_POLICY
from clue_research.stage0.seeds_types import (
    DEFAULT_SEED_POLICY,
    SeedPolicy,
    SeedReason,
    SeedSet,
    SkippedSeed,
    is_customer_reason,
    reason_rank,
)
from clue_research.stage0.types import ClientKnowledgeBaseRef

_MODE_DISCOVERY = ResearchMode.ACCOUNT_DISCOVERY  # the seed marker rides the discovery flavor


def seeds_run_id(client_id: str, icp_spec_ref: ICPSpecRef) -> RunId:
    """The deterministic run id for a seed-assembly pass — a re-run for the same client+ICP
    re-writes the seed markers under one stable run, so re-assembly stays idempotent on
    ``(entity, field, source, run)`` rather than accreting duplicate markers."""
    return RunId(
        uuid5(
            NAMESPACE_URL,
            f"seed:{client_id}:{icp_spec_ref.icp_key}:{icp_spec_ref.icp_version}",
        )
    )


async def assemble_lookalike_seeds(
    conn: AsyncConnection,
    icp_spec_ref: ICPSpecRef,
    client_kb_ref: ClientKnowledgeBaseRef,
    *,
    import_result: ImportResult | None = None,
    policy: SeedPolicy = DEFAULT_SEED_POLICY,
    enabled: bool = True,
    run_id: RunId | None = None,
) -> SeedSet:
    """Assemble + rank lookalike seeds for the ICP referenced by ``icp_spec_ref`` from the client's
    existing customers (``client_kb_ref``) and resolved imports (``import_result``).

    Returns a :class:`~clue_research.stage0.seeds_types.SeedSet` of resolved ``account_entity``
    seeds, each with a ``seed_reason`` and a blended ``seed_confidence``, partitioned to **this**
    ICP (a candidate must clear the ICP's own fit floor). ``enabled=False`` is the hybrid opt-out:
    it returns a suppressed empty SeedSet and writes nothing. Run inside a transaction (each chosen
    seed gets one discovery-provenance marker that commits with the rest).

    **Preconditions:** ``import_result`` must have been back-scored against this same
    ``icp_spec_ref`` (the wired hybrid same-ICP flow); its in-memory fit scores are the import
    partition signal (spec: "using M5.3 back-scores where available"). Reusing one ``import_result``
    across *different* ICPs (a multi-ICP client, D5) would mis-partition imports — score each ICP's
    imports against that ICP. Customer evidence carries no back-score, so it is scored fresh against
    the target ICP here and partitions correctly regardless (the asymmetry tracks availability).
    """
    client_id = icp_spec_ref.client_id
    client_entity_id = client_kb_ref.client_entity_id

    if not enabled:  # hybrid opt-out (Doc B §1) — suppressed set, import-only path intact
        return SeedSet(
            client_id=client_id,
            icp_key=icp_spec_ref.icp_key,
            icp_version=icp_spec_ref.icp_version,
            suppressed=True,
        )

    scope = TenantScope.for_tenant(client_id)
    run = run_id if run_id is not None else seeds_run_id(client_id, icp_spec_ref)

    with traced_step("stage0.assemble_lookalike_seeds", **{ATTR_CLIENT_ID: client_id}):
        # Resolve the client to its current survivor once: client_kb_ref captured the entity at
        # reverse-profiling time, so a later merge could leave it a non-survivor — comparing the
        # raw id would let the client slip through as its own lookalike seed (conventions §2: key on
        # the resolved entity_id). surviving_id is a no-op when nothing merged.
        client_survivor = await surviving_id(
            conn, client_kb_ref.client_entity_id, EntityType.ACCOUNT
        )

        rubric = await get_rubric_version(
            conn, client_id, icp_spec_ref.icp_key, icp_spec_ref.icp_version
        )
        floor = _fit_floor(rubric)

        candidates: dict[EntityId, _Candidate] = {}

        # Sources 2 + 3 — resolved imports. Their fit is the M5.3 in-memory back-score (the spec's
        # "using M5.3 back-scores where available"); the documented precondition is that the
        # ``import_result`` was scored against *this* ``icp_spec_ref`` (the wired hybrid same-ICP
        # flow). Customer evidence below has no back-score, so it is scored fresh — the asymmetry
        # tracks data availability, not an oversight.
        if import_result is not None:
            for acc in import_result.resolved:
                survivor = await surviving_id(conn, acc.account_entity_id, EntityType.ACCOUNT)
                if survivor == client_survivor:
                    continue  # a client is never a lookalike seed of itself
                if acc.fit_flag is not FitFlag.FIT:
                    # D6: a non-fit import is excluded from seeding (kept in the list, not seeded).
                    continue
                reason = (
                    SeedReason.CRM_CUSTOMER if acc.already_customer else SeedReason.HIGH_FIT_IMPORT
                )
                _consider(
                    candidates,
                    entity_id=survivor,
                    reason=reason,
                    fit=acc.fit_score.value,
                    resolution_confidence=acc.resolution_confidence,
                    justifying=(acc.provenance_claim_id,),
                    policy=policy,
                )

        # Source 1 — existing-customer evidence from the Client Knowledge Base (M5.1).
        skipped: list[SkippedSeed] = []
        for entry, justifying_id in await _customer_evidence(
            conn, client_entity_id, client_id=client_id, version=client_kb_ref.client_kb_version
        ):
            resolved = await _resolve_customer(
                conn, entry, policy, client_id=client_id, client_entity_id=client_survivor
            )
            if resolved is None:
                skipped.append(
                    SkippedSeed(
                        identity_repr=_customer_repr(entry),
                        reason="customer evidence did not resolve to a clean known entity",
                    )
                )
                continue
            entity_id, resolution_confidence = resolved
            fit = await _score_fit(conn, rubric, entity_id, scope)
            _consider(
                candidates,
                entity_id=entity_id,
                reason=SeedReason.EXISTING_CUSTOMER,
                fit=fit,
                resolution_confidence=resolution_confidence,
                justifying=(justifying_id,),
                policy=policy,
            )

        chosen = _rank_and_gate(candidates, policy=policy, fit_floor=floor)

        seeds: list[SeedAccount] = []
        for cand in chosen:
            provenance_id = await _write_seed_provenance(
                conn,
                entity_id=cand.entity_id,
                reason=cand.reason,
                icp_spec_ref=icp_spec_ref,
                seed_confidence=cand.seed_confidence,
                run_id=run,
                client_id=client_id,
            )
            seeds.append(
                SeedAccount(
                    account_entity_id=cand.entity_id,
                    seed_reason=cand.reason.value,
                    seed_confidence=cand.seed_confidence,
                    justifying_claim_ids=(*cand.justifying, provenance_id),
                )
            )

    return SeedSet(
        client_id=client_id,
        icp_key=icp_spec_ref.icp_key,
        icp_version=icp_spec_ref.icp_version,
        seeds=tuple(seeds),
        suppressed=False,
        skipped=tuple(skipped),
        channels=_seed_channels(chosen),
    )


# --- candidate accumulation + ranking --------------------------------------


@dataclass(frozen=True)
class _Candidate:
    """One seed candidate accumulated during assembly — deduped by ``entity_id`` (an entity surfaced
    by more than one source keeps the strongest anchor, see :func:`_consider`)."""

    entity_id: EntityId
    reason: SeedReason
    fit: float
    resolution_confidence: float
    justifying: tuple[ClaimId, ...]
    seed_confidence: float


def _consider(
    candidates: dict[EntityId, _Candidate],
    *,
    entity_id: EntityId,
    reason: SeedReason,
    fit: float,
    resolution_confidence: float,
    justifying: tuple[ClaimId | None, ...],
    policy: SeedPolicy,
) -> None:
    """Add (or merge) a candidate. When one entity is surfaced by several sources, keep the stronger
    anchor (by ``(reason_rank, seed_confidence)``) and **union** the justifying claim ids — so a
    customer that is also a high-fit import is recorded as the customer with both justifications."""
    seed_confidence = policy.seed_confidence(
        resolution_confidence=resolution_confidence,
        fit=fit,
        is_customer=is_customer_reason(reason),
    )
    just = tuple(j for j in justifying if j is not None)
    incoming = _Candidate(
        entity_id=entity_id,
        reason=reason,
        fit=fit,
        resolution_confidence=resolution_confidence,
        justifying=just,
        seed_confidence=seed_confidence,
    )
    current = candidates.get(entity_id)
    if current is None:
        candidates[entity_id] = incoming
        return
    merged_justifying = tuple(dict.fromkeys((*current.justifying, *incoming.justifying)))
    stronger = (
        incoming
        if (reason_rank(reason), seed_confidence)
        > (reason_rank(current.reason), current.seed_confidence)
        else current
    )
    candidates[entity_id] = _Candidate(
        entity_id=entity_id,
        reason=stronger.reason,
        fit=stronger.fit,
        resolution_confidence=stronger.resolution_confidence,
        justifying=merged_justifying,
        seed_confidence=stronger.seed_confidence,
    )


def _rank_and_gate(
    candidates: dict[EntityId, _Candidate], *, policy: SeedPolicy, fit_floor: float
) -> list[_Candidate]:
    """Rank candidates by ``seed_confidence`` (desc) and keep only clean, fitting anchors: a
    candidate must clear ``min_resolution_confidence`` (clean identity), ``min_seed_confidence``
    (the soft floor), and the ICP's own ``fit_floor`` (the per-ICP partition — D5/D6). Capped at
    ``max_seeds``."""
    ranked = sorted(candidates.values(), key=lambda c: c.seed_confidence, reverse=True)
    chosen: list[_Candidate] = []
    for cand in ranked:
        if cand.resolution_confidence < policy.min_resolution_confidence:
            continue
        if cand.seed_confidence < policy.min_seed_confidence:
            continue
        if fit_floor > 0.0 and cand.fit < fit_floor:
            continue  # a non-fit anchor would seed non-fit lookalikes (per-ICP partition)
        chosen.append(cand)
        if len(chosen) >= policy.max_seeds:
            break
    return chosen


def _seed_channels(chosen: list[_Candidate]) -> tuple[str, ...]:
    """The lookalike-expansion channels these seeds will anchor — the coverage-confidence framing
    input M6 / Doc C §7 reporting consumes (M5.4 supplies the channels, not the estimate itself)."""
    channels = {
        "lookalike_customer" if is_customer_reason(c.reason) else "lookalike_import" for c in chosen
    }
    return tuple(sorted(channels))


# --- scoring (per-ICP partition) -------------------------------------------


def _fit_floor(rubric: ScoringRubric | None) -> float:
    """The ICP-relative fit floor via the shared M3.4 :func:`~clue_research.icp.fit_floor` (the same
    threshold M5.3's non-fit flag uses, single-sourced so the two never drift). ``0.0`` (no rubric /
    no band) means the ICP set no bar."""
    return 0.0 if rubric is None else fit_floor(rubric.tier_cutoffs)


async def _score_fit(
    conn: AsyncConnection, rubric: ScoringRubric | None, entity_id: EntityId, scope: TenantScope
) -> float:
    """Back-score one candidate's fit against the **target** ICP via the M3.4 scorer (the importable
    Pass-A primitive M5.3/M6 use). An entity with no scorable claims back-scores ``0.0`` — honestly
    excluded by any fit floor rather than seeded blind."""
    if rubric is None:
        return 0.0
    result = await score_entity(conn, rubric, entity_id, scope=scope)
    return result.fit_score


# --- existing-customer evidence (source 1) ---------------------------------


async def _customer_evidence(
    conn: AsyncConnection,
    client_entity_id: EntityId,
    *,
    client_id: str,
    version: int | None,
) -> list[tuple[dict[str, JsonValue], ClaimId | None]]:
    """Read the ``client.customer`` evidence list from the pinned Client Knowledge Base version,
    each paired with the claim id that justifies it (so a seed derived from it cites that client
    fact). Returns ``[]`` when the client has no customers-page / CRM customer evidence."""
    claims = await read_client_kb_claims(
        conn, client_entity_id, client_id=client_id, version=version
    )
    claim = claims.get(CLIENT_CUSTOMER)
    if claim is None or not isinstance(claim.value_json, list):
        return []
    return [(entry, claim.id) for entry in claim.value_json if isinstance(entry, dict)]


async def _resolve_customer(
    conn: AsyncConnection,
    entry: dict[str, JsonValue],
    policy: SeedPolicy,
    *,
    client_id: str,
    client_entity_id: EntityId,
) -> tuple[EntityId, float] | None:
    """Resolve one customer-evidence entry to a clean ``account_entity`` via the M2 identity
    service.

    A deterministic / high-confidence match (``>= min_resolution_confidence``) reuses the survivor.
    Otherwise, only if ``policy.admit_unmatched_customers`` *and* the entry carries a registrable
    domain, a fresh ``candidate`` entity is admitted (client-asserted, existence-gated on the
    domain); a name-only or low-confidence entry returns ``None`` (surfaced in ``skipped``, never
    guessed). A self-match to the client's own entity is dropped (a client is not its own seed)."""
    name = entry.get("name")
    domain = entry.get("domain")
    name_str = str(name) if name else ""
    domain_str = str(domain) if domain else None
    if not (name_str or domain_str):
        return None

    result = await resolve(
        conn,
        Observation(name=name_str, entity_type=EntityType.ACCOUNT, domain=domain_str),
    )
    if result.top is not None and result.top_score >= policy.min_resolution_confidence:
        entity_id = await surviving_id(conn, result.top.entity_id, EntityType.ACCOUNT)
        if entity_id == client_entity_id:
            return None
        return entity_id, result.top_score

    if policy.admit_unmatched_customers and domain_str and registrable_domain(domain_str):
        entity_id = await insert_account_entity(
            conn,
            canonical_name=name_str or domain_str,
            primary_domain=domain_str,
            aliases=(name_str,) if name_str else (),
            status=AccountStatus.CANDIDATE,
        )
        await embed_account(conn, entity_id)  # so the next pass resolves to it (no duplicate)
        return (
            entity_id,
            1.0,
        )  # the client asserts this is their customer → full identity confidence
    return None


def _customer_repr(entry: dict[str, JsonValue]) -> str:
    name = entry.get("name")
    domain = entry.get("domain")
    return str(name or domain or "")


# --- seed-derivation provenance --------------------------------------------


async def _write_seed_provenance(
    conn: AsyncConnection,
    *,
    entity_id: EntityId,
    reason: SeedReason,
    icp_spec_ref: ICPSpecRef,
    seed_confidence: float,
    run_id: RunId,
    client_id: str,
) -> ClaimId:
    """Record the seed-derivation as a discovery-flavored claim (``matched_channel='seed'``) on the
    seed entity — so a lookalike candidate M6 derives can cite its anchor ("lookalike of your
    customer Acme"), and the seed selection is auditable with the rest of the store. The
    ``insert_claim`` call skips the field-registry check for discovery claims, so the marker needs
    no registered field.

    Stamped **tenant-private**: the account entity is cross-tenant-shared, but *which accounts a
    client seeds lookalikes from for their ICP* is client-tuned, competitively-sensitive intent (the
    same class as the import provenance), so it never amortizes across tenants.

    **Idempotent** on the deterministic ``run_id``: a re-assembly for the same client+ICP finds the
    existing live seed marker (same run, ``matched_channel='seed'``) and reuses it rather than
    appending a duplicate — so re-running keeps one marker per seed and a stable
    ``justifying_claim_ids`` (the store has no unique constraint to lean on, so the guard is an
    explicit read, mirroring the M4 waterfall's idempotent-skip)."""
    existing = await claims_for(
        conn, entity_id, DISCOVERY_PROVENANCE, scope=TenantScope.for_tenant(client_id)
    )
    for prior in existing:
        if (
            prior.run_id == run_id
            and isinstance(prior.value_json, dict)
            and prior.value_json.get("matched_channel") == "seed"
        ):
            return prior.id  # already written this run → idempotent reuse, no duplicate marker
    claim = discovery_claim(
        entity_id=entity_id,
        entity_type=EntityType.ACCOUNT,
        field_key=DISCOVERY_PROVENANCE,
        value_json={
            "matched_channel": "seed",
            "seed_reason": reason.value,
            "icp_key": icp_spec_ref.icp_key,
            "icp_version": icp_spec_ref.icp_version,
            "seed_confidence": seed_confidence,
        },
        source_tier=1,
        # derived from client-supplied customers / imports
        extraction_method=ExtractionMethod.HUMAN,
        confidence=1.0,
        run_id=run_id,
        research_mode=_MODE_DISCOVERY,
        found_via=f"seed:{reason.value}",
        matched_signal=reason.value,
        discovery_confidence=seed_confidence,
        evidence_span=(
            f"lookalike seed ({reason.value}) for ICP "
            f"{icp_spec_ref.icp_key} v{icp_spec_ref.icp_version}"
        ),
    )
    claim = stamp_reuse(claim, tenant_id=client_id, policy=SEED_REUSE_POLICY)
    return await insert_claim(conn, claim)
