"""DB-backed tests for M5.4 — hybrid lookalike seeding (``assemble_lookalike_seeds``).

Covers every acceptance criterion: seeds assembled from existing customers (M5.1 evidence) +
resolved imports (M5.3) each carry a ``seed_reason`` + ``seed_confidence``; seeds are partitioned
per ICP (a segment-A customer seeds only the segment-A ICP — D5); low-fit / low-confidence
candidates are filtered (a non-fit import is excluded from seeding — D6 — yet stays in the
researched list); the hybrid opt-out yields a suppressed SeedSet without breaking the import-only
path; every seed is a resolved ``account_entity`` carrying a discovery-provenance 'seed' marker a
mock M6 consumer can cite; and no seed is ever a free-text name. Also verifies the hybrid seam
end-to-end: a SeedSet's seeds slot into an ICP proposal → confirm → the compiled spec's
``discovery_strategy.seed_account_ids``.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import TenantScope, claims_for, insert_claim
from clue_research.core import (
    AccountStatus,
    EntityId,
    ExtractionMethod,
    ResearchMode,
    ReuseScope,
    Score,
    account_claim,
    new_run_id,
)
from clue_research.icp import get_active_icp
from clue_research.identity import (
    DEFAULT_REUSE_POLICY,
    embed_account,
    get_account,
    insert_account_entity,
    stamp_reuse,
)
from clue_research.stage0 import (
    DISCOVERY_PROVENANCE,
    FirmographicDimensions,
    FitFlag,
    ICPProposal,
    ImportResult,
    ProposedRubric,
    ResolvedAccount,
    RubricWeight,
    SeedAccount,
    SeedPolicy,
    SeedReason,
    assemble_lookalike_seeds,
    confirm_icp,
)
from clue_research.stage0.types import ClientKnowledgeBaseRef
from tests.stage0._fakes import (
    build_client_kb,
    build_confirmed_icp,
    build_confirmed_icp_on_field,
)
from tests.stage0.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_stage0_db", "resolver_bindings")

_CLIENT = "tenant-seed"
_EMP = "core.employee_count"
_FUNDING = "account.recent_funding"


def _scope() -> TenantScope:
    return TenantScope.for_tenant(_CLIENT)


async def _account(
    conn: AsyncConnection,
    suffix: str,
    *,
    domain: str,
    status: AccountStatus = AccountStatus.CANDIDATE,
) -> EntityId:
    """A resolved + embedded account entity (so the customer-evidence resolver finds it)."""
    entity_id = await insert_account_entity(
        conn, canonical_name=f"Acct {suffix}", primary_domain=domain, status=status
    )
    await embed_account(conn, entity_id)
    return entity_id


async def _write_field(
    conn: AsyncConnection, entity_id: EntityId, field_key: str, value: JsonValue
) -> None:
    """Write one public account-field claim so the entity back-scores against a rubric on it."""
    claim = account_claim(
        entity_id=entity_id,
        field_key=field_key,
        value_json=value,
        source_tier=1,
        extraction_method=ExtractionMethod.API,
        confidence=1.0,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://seed-evidence.example",
        evidence_span="seed test fixture",
    )
    claim = stamp_reuse(claim, tenant_id=_CLIENT, policy=DEFAULT_REUSE_POLICY)
    await insert_claim(conn, claim)


async def _kb_with_customers(
    conn: AsyncConnection, suffix: str, customers: list[dict[str, JsonValue]]
) -> ClientKnowledgeBaseRef:
    """A Client KB whose ``client.customer`` evidence names ``customers`` (name/domain dicts)."""
    return await build_client_kb(
        conn,
        client_id=_CLIENT,
        suffix=suffix,
        asserted={"client.customer": customers},
    )


def _resolved(
    entity_id: EntityId,
    *,
    fit: float,
    flag: FitFlag,
    already_customer: bool = False,
    resolution_confidence: float = 1.0,
) -> ResolvedAccount:
    """A ResolvedAccount as M5.3's ``import_accounts`` would emit (back-scores are in-memory)."""
    return ResolvedAccount(
        account_entity_id=entity_id,
        row_index=1,
        fit_score=Score(value=fit),
        intent_score=Score(value=0.0),
        fit_flag=flag,
        already_customer=already_customer,
        resolution_method="deterministic",
        matched_signal="domain",
        resolution_confidence=resolution_confidence,
    )


def _imports(*resolved: ResolvedAccount) -> ImportResult:
    return ImportResult(import_batch_id="b", resolved=tuple(resolved))


# --- AC1: seeds from imports + existing customers ---------------------------


def test_assembles_seeds_from_imports_and_customers() -> None:
    """Given reverse-profiled customers + an imported list, the SeedSet carries resolved entities,
    each with a seed_reason + seed_confidence (AC1)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            icp = await build_confirmed_icp_on_field(
                conn, client_id=_CLIENT, icp_key="primary", fit_field=_EMP
            )
            # an existing customer (named on the customers page, has firmographic signal → fits)
            cust = await _account(conn, "cust", domain="cust.example")
            await _write_field(conn, cust, _EMP, 250)
            kb = await _kb_with_customers(
                conn, "ac1", [{"name": "Cust Co", "domain": "cust.example"}]
            )
            # a CRM existing customer surfaced by the import pipeline (FIT, already_customer)
            crm = await _account(conn, "crm", domain="crm.example")
            imports = _imports(_resolved(crm, fit=1.0, flag=FitFlag.FIT, already_customer=True))

            seeds = await assemble_lookalike_seeds(conn, icp, kb, import_result=imports)

            assert seeds.seed_count == 2
            by_entity = {s.account_entity_id: s for s in seeds.seeds}
            assert by_entity[cust].seed_reason == SeedReason.EXISTING_CUSTOMER.value
            assert by_entity[crm].seed_reason == SeedReason.CRM_CUSTOMER.value
            assert all(s.seed_confidence > 0.0 for s in seeds.seeds)
            assert "lookalike_customer" in seeds.channels

    run_async(_run())


# --- AC2: per-ICP partition (D5) -------------------------------------------


def test_seeds_partitioned_per_icp() -> None:
    """A customer that fits segment A but not segment B seeds only the segment-A ICP (D5)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            seg_a = await build_confirmed_icp_on_field(
                conn, client_id=_CLIENT, icp_key="seg_a", fit_field=_EMP
            )
            seg_b = await build_confirmed_icp_on_field(
                conn, client_id=_CLIENT, icp_key="seg_b", fit_field=_FUNDING
            )
            # the customer has employee_count (segment A) but no recent_funding (segment B)
            cust = await _account(conn, "seg", domain="seg.example")
            await _write_field(conn, cust, _EMP, 500)
            kb = await _kb_with_customers(
                conn, "ac2", [{"name": "Seg Co", "domain": "seg.example"}]
            )

            a = await assemble_lookalike_seeds(conn, seg_a, kb)
            b = await assemble_lookalike_seeds(conn, seg_b, kb)

            assert cust in {s.account_entity_id for s in a.seeds}  # fits segment A → seeded
            assert cust not in {s.account_entity_id for s in b.seeds}  # not segment B → excluded
            assert b.seed_count == 0  # the customer resolves but is below segment B's fit floor
            # it is a partition decision, not a resolution failure → not surfaced as skipped
            assert b.skipped == ()

    run_async(_run())


# --- AC3 + D6: low-fit / low-confidence filtered ---------------------------


def test_non_fit_import_excluded_but_kept_in_list() -> None:
    """A non-fit import is excluded from seeding (D6: a non-fit anchor seeds non-fit lookalikes) but
    remains in the researched import list; a high-fit import is seeded."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            icp = await build_confirmed_icp_on_field(
                conn, client_id=_CLIENT, icp_key="primary", fit_field=_EMP
            )
            fit_acct = await _account(conn, "fit", domain="fit.example")
            misfit = await _account(conn, "misfit", domain="misfit.example")
            imports = _imports(
                _resolved(fit_acct, fit=0.9, flag=FitFlag.FIT),
                _resolved(misfit, fit=0.1, flag=FitFlag.NON_FIT),
            )
            kb = await _kb_with_customers(conn, "ac3", [])

            seeds = await assemble_lookalike_seeds(conn, icp, kb, import_result=imports)

            seeded = {s.account_entity_id for s in seeds.seeds}
            assert fit_acct in seeded
            assert misfit not in seeded  # excluded from seeding ...
            assert misfit in {r.account_entity_id for r in imports.resolved}  # ... but kept in list
            assert seeds.seeds[0].seed_reason == SeedReason.HIGH_FIT_IMPORT.value
            # the import-only seed set anchors the lookalike_import channel (coverage framing)
            assert seeds.channels == ("lookalike_import",)

    run_async(_run())


def test_low_resolution_confidence_customer_filtered() -> None:
    """A customer evidence entry that does not resolve to a clean known entity is filtered into
    skipped[] (not guessed into a seed) — clean anchors only (AC3)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            icp = await build_confirmed_icp_on_field(
                conn, client_id=_CLIENT, icp_key="primary", fit_field=_EMP
            )
            # a customers-page name with no matching store entity (default policy doesn't admit it)
            kb = await _kb_with_customers(
                conn, "ac3b", [{"name": "Ghost Co", "domain": "ghost-unknown.example"}]
            )
            seeds = await assemble_lookalike_seeds(conn, icp, kb)
            assert seeds.seed_count == 0
            assert any(sk.identity_repr == "Ghost Co" for sk in seeds.skipped)

    run_async(_run())


def test_low_resolution_confidence_import_filtered() -> None:
    """A FIT import resolved at low identity confidence is filtered out (the resolution-confidence
    gate is load-bearing only for imports — customers are already gated at resolve time); a
    cleanly-resolved FIT import is kept (AC3 — clean anchors only)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            icp = await build_confirmed_icp_on_field(
                conn, client_id=_CLIENT, icp_key="primary", fit_field=_EMP
            )
            clean = await _account(conn, "clean", domain="clean.example")
            dirty = await _account(conn, "dirty", domain="dirty.example")
            imports = _imports(
                _resolved(clean, fit=0.9, flag=FitFlag.FIT, resolution_confidence=1.0),
                # below DEFAULT_SEED_POLICY.min_resolution_confidence=0.85 → a dirty anchor
                _resolved(dirty, fit=0.9, flag=FitFlag.FIT, resolution_confidence=0.6),
            )
            kb = await _kb_with_customers(conn, "lc", [])
            seeds = await assemble_lookalike_seeds(conn, icp, kb, import_result=imports)
            seeded = {s.account_entity_id for s in seeds.seeds}
            assert clean in seeded
            assert dirty not in seeded

    run_async(_run())


def test_import_resolving_to_client_is_not_self_seeded() -> None:
    """An import whose resolved entity is the client itself is never a lookalike seed of the client
    (the M2 survivor invariant — conventions §2)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            icp = await build_confirmed_icp_on_field(
                conn, client_id=_CLIENT, icp_key="primary", fit_field=_EMP
            )
            kb = await _kb_with_customers(conn, "self", [])
            # an import row that resolved to the client's own entity (a degenerate but real case)
            imports = _imports(_resolved(kb.client_entity_id, fit=1.0, flag=FitFlag.FIT))
            seeds = await assemble_lookalike_seeds(conn, icp, kb, import_result=imports)
            assert kb.client_entity_id not in {s.account_entity_id for s in seeds.seeds}
            assert seeds.seed_count == 0

    run_async(_run())


def test_admit_unmatched_customers_mints_candidate_when_enabled() -> None:
    """With ``admit_unmatched_customers`` on, a customers-page entry with a usable domain but no
    store entity is admitted as a fresh candidate (client-asserted, existence-gated on the domain);
    a name-only entry is still surfaced in skipped[] (the docstring promise) and mints nothing."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            # no fit floor → the freshly-admitted (claim-less) candidate is not gated out on fit
            icp = await build_confirmed_icp_on_field(
                conn, client_id=_CLIENT, icp_key="primary", fit_field=_EMP, fit_threshold=0.0
            )
            kb = await _kb_with_customers(
                conn,
                "admit",
                [
                    {"name": "Fresh Co", "domain": "fresh-unseen.example"},  # admitted
                    {"name": "Nameonly Co"},  # no domain → skipped even with admit on
                ],
            )
            policy = SeedPolicy(admit_unmatched_customers=True)
            seeds = await assemble_lookalike_seeds(conn, icp, kb, policy=policy)

            assert seeds.seed_count == 1
            (seed,) = seeds.seeds
            assert seed.seed_reason == SeedReason.EXISTING_CUSTOMER.value
            # the admitted seed is a real candidate account entity, resolvable by its domain
            entity = await get_account(conn, seed.account_entity_id)
            assert entity is not None and entity.status is AccountStatus.CANDIDATE
            # the name-only entry is surfaced, not minted
            assert any(sk.identity_repr == "Nameonly Co" for sk in seeds.skipped)

    run_async(_run())


# --- AC4: hybrid opt-out ---------------------------------------------------


def test_opt_out_yields_suppressed_seedset() -> None:
    """enabled=False returns a suppressed, empty SeedSet and writes nothing — the import-only path
    is left intact (always-has-the-wheel, AC4)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            icp = await build_confirmed_icp(conn, client_id=_CLIENT)
            cust = await _account(conn, "optout", domain="optout.example")
            await _write_field(conn, cust, _EMP, 100)
            kb = await _kb_with_customers(
                conn, "ac4", [{"name": "Opt Co", "domain": "optout.example"}]
            )
            seeds = await assemble_lookalike_seeds(conn, icp, kb, enabled=False)
            assert seeds.suppressed is True
            assert seeds.seed_count == 0
            assert seeds.skipped == ()
            # nothing was written: no seed-provenance marker exists on the customer entity
            markers = await claims_for(conn, cust, field_key=DISCOVERY_PROVENANCE, scope=_scope())
            assert not markers

    run_async(_run())


# --- AC5 + AC6: resolved seed + provenance + mock M6 consumer ---------------


def test_seed_is_resolved_entity_with_provenance_and_mock_consumer() -> None:
    """Every seed is a resolved account_entity carrying a tenant-private discovery-provenance 'seed'
    marker a downstream candidate can cite; a mock M6 consumer reads the SeedSet (AC5/AC6)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            icp = await build_confirmed_icp_on_field(
                conn, client_id=_CLIENT, icp_key="primary", fit_field=_EMP
            )
            cust = await _account(conn, "prov", domain="prov.example")
            await _write_field(conn, cust, _EMP, 300)
            kb = await _kb_with_customers(
                conn, "ac5", [{"name": "Prov Co", "domain": "prov.example"}]
            )
            seeds = await assemble_lookalike_seeds(conn, icp, kb)

            (seed,) = seeds.seeds
            # AC6: the seed is a resolved entity id (the customer's), not a free-text name
            from uuid import UUID

            assert isinstance(seed.account_entity_id, UUID)
            assert seed.account_entity_id == cust  # resolved through M2, not the page's free text
            entity = await get_account(conn, seed.account_entity_id)
            assert entity is not None
            # AC5: it carries a discovery-provenance 'seed' marker, tenant-private, with the reason
            markers = await claims_for(
                conn, seed.account_entity_id, field_key=DISCOVERY_PROVENANCE, scope=_scope()
            )
            assert markers
            marker = markers[0]
            assert marker.value_json["matched_channel"] == "seed"
            assert marker.value_json["seed_reason"] == SeedReason.EXISTING_CUSTOMER.value
            assert marker.value_json["icp_key"] == "primary"
            assert marker.reuse_scope is ReuseScope.TENANT_PRIVATE
            assert marker.tenant_id == _CLIENT
            assert marker.discovery_provenance is not None
            # the seed cites both the client customer claim and its own seed marker
            assert seed.justifying_claim_ids
            # a mock M6 lookalike-expansion consumer reads the SeedSet (the seam)
            citations = _mock_m6_lookalike(seeds.seeds)
            assert citations == [f"lookalike of {SeedReason.EXISTING_CUSTOMER.value}"]

    run_async(_run())


def _mock_m6_lookalike(seeds: Sequence[SeedAccount]) -> list[str]:
    """A stand-in for M6 mode-M1 lookalike expansion: it consumes resolved seed ids + reasons and
    would expand each into 'companies like this one'. Here it just proves the SeedSet is shape-valid
    input (it reads only the public contract: account_entity_id + seed_reason)."""
    return [f"lookalike of {s.seed_reason}" for s in seeds]


# --- dedup: a customer that is also an import keeps the customer anchor ------


def test_entity_in_both_sources_dedups_to_stronger_anchor() -> None:
    """An entity surfaced as both a high-fit import and an existing customer is seeded once, as the
    customer (the stronger anchor), with both justifications unioned."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            icp = await build_confirmed_icp_on_field(
                conn, client_id=_CLIENT, icp_key="primary", fit_field=_EMP
            )
            both = await _account(conn, "both", domain="both.example")
            await _write_field(conn, both, _EMP, 400)
            kb = await _kb_with_customers(
                conn, "dedup", [{"name": "Both Co", "domain": "both.example"}]
            )
            imports = _imports(_resolved(both, fit=1.0, flag=FitFlag.FIT, already_customer=False))

            seeds = await assemble_lookalike_seeds(conn, icp, kb, import_result=imports)

            assert seeds.seed_count == 1  # one entity, one seed (not double-counted)
            (seed,) = seeds.seeds
            assert seed.seed_reason == SeedReason.EXISTING_CUSTOMER.value  # customer > import
            assert len(seed.justifying_claim_ids) >= 2  # the customer claim + the seed marker

    run_async(_run())


# --- the hybrid seam: SeedSet → proposal → confirm → spec discovery strategy -


def test_seeds_flow_into_proposal_confirm_and_spec() -> None:
    """A SeedSet's seeds slot straight into an ICP proposal; confirm compiles them into the spec's
    discovery_strategy.seed_account_ids — the store/spec-mediated path M6 reads (no sibling import).
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            icp = await build_confirmed_icp_on_field(
                conn, client_id=_CLIENT, icp_key="primary", fit_field=_EMP
            )
            cust = await _account(conn, "seam", domain="seam.example")
            await _write_field(conn, cust, _EMP, 700)
            kb = await _kb_with_customers(
                conn, "seam", [{"name": "Seam Co", "domain": "seam.example"}]
            )
            seeds = await assemble_lookalike_seeds(conn, icp, kb)
            assert seeds.seed_count == 1

            proposal = ICPProposal(
                icp_key="hybrid",
                firmographic=FirmographicDimensions(field_keys=(_EMP,)),
                rubric=ProposedRubric(
                    weights=(
                        RubricWeight(
                            field_key=_EMP, dimension="fit", weight=1.0, transform="boolean"
                        ),
                    ),
                    fit_threshold=0.5,
                ),
                seed_accounts=seeds.seeds,  # M5.4 output IS the proposal's seed_accounts
            )
            confirmation = await confirm_icp(
                conn,
                proposal,
                client_id=_CLIENT,
                client_entity_id=kb.client_entity_id,
            )
            spec = await get_active_icp(conn, _CLIENT, confirmation.ref.icp_key)
            assert spec is not None
            seed_ids = spec.discovery_strategy["seed_account_ids"]
            assert str(cust) in seed_ids
            assert spec.discovery_strategy["mode"] == "lookalike"  # seeds present → lookalike mode

    run_async(_run())


# --- determinism: re-assembly is stable ------------------------------------


def test_reassembly_is_stable() -> None:
    """Re-assembling for the same client+ICP yields the same seed set (deterministic run id; the
    seed markers re-write idempotently under one stable run)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            icp = await build_confirmed_icp_on_field(
                conn, client_id=_CLIENT, icp_key="primary", fit_field=_EMP
            )
            cust = await _account(conn, "stable", domain="stable.example")
            await _write_field(conn, cust, _EMP, 600)
            kb = await _kb_with_customers(
                conn, "stable", [{"name": "Stable Co", "domain": "stable.example"}]
            )
            first = await assemble_lookalike_seeds(conn, icp, kb)
            second = await assemble_lookalike_seeds(conn, icp, kb)
            assert [s.account_entity_id for s in first.seeds] == [
                s.account_entity_id for s in second.seeds
            ]
            assert [s.seed_reason for s in first.seeds] == [s.seed_reason for s in second.seeds]
            # idempotent write: re-assembly reuses the existing 'seed' marker, never accreting a
            # duplicate under the deterministic run id (and justifying_claim_ids stays stable)
            markers = await claims_for(conn, cust, field_key=DISCOVERY_PROVENANCE, scope=_scope())
            seed_markers = [
                m
                for m in markers
                if isinstance(m.value_json, dict) and m.value_json.get("matched_channel") == "seed"
            ]
            assert len(seed_markers) == 1
            assert first.seeds[0].justifying_claim_ids == second.seeds[0].justifying_claim_ids

    run_async(_run())
