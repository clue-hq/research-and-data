"""The deep-profiling composition root — where the independent milestone packages are wired.

The import-linter *independence* contract keeps the milestone worker packages (M4 ``sources``,
M7 ``durable``, M8 ``profiling``, M9 ``verification``, …) from importing one another; they meet
**only here** (``api`` is the exempt seam — nothing imports ``api``, Rule 5). This is the single
coordination point the M8 kickoff/handoff calls out: it

* loads every field pack + source manifest a deep run reads (:func:`load_research_packs`);
* constructs the M8 deep-profiling :class:`~clue_core.execution.AspectWorker`\\s with their
  injected dependencies and registers them into the M7
  :class:`~clue_research.durable.WorkerRegistry`
  (:func:`build_profiling_workers` / :func:`build_worker_registry`); the two axes carry disjoint
  aspect keys (``account`` / ``account.resonance`` vs ``committee`` / ``contact.facet``) so they
  compose without collision;
* injects the M9 governance seams — the authoritative ``verification.classify_binding`` behind
  M8.4's :class:`~clue_research.profiling.contact.binding.BindingClassifier`
  (:class:`VerificationBindingClassifier`, the deferred M9.4×M8.4 stamp) and the
  :class:`~clue_core.verification.PreSpendGate` the account-axis worker consults before
  spend (:func:`build_pre_spend_gate`, the deferred M9.1 routing).

Not yet wired here (still deferred — they need worker/M7 code changes, not pure composition, and are
flagged in CLAUDE.md): the committee/contact pre-spend-gate call sites (no seam on those workers
yet) and threading the campaign coordinates (``workspace_id`` / ``icp_key`` / ``icp_version`` /
``account_entity_id``) into the graph-built ``AspectContext.params`` so committee/contact dispatch
in-graph (today they are driven via their direct callables, which populate those explicitly).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import RecursionPolicy
from clue_core import (
    ClaimId,
    EntityId,
    IdentityBinding,
    LLMGateway,
    PreSpendGate,
    new_claim_id,
)
from clue_core.execution import AspectWorker
from clue_db import ConnFactory, transaction
from clue_research.claimstore import load_core_pack
from clue_research.durable import (
    AccountResearchGraph,
    WorkerRegistry,
)
from clue_research.profiling import (
    SynthesisGuard,
    account_axis_workers,
    load_committee_pack,
    load_deep_profiling_pack,
)
from clue_research.profiling.committee import CommitteeAspectWorker, CommitteeSource
from clue_research.profiling.contact import ContactProfileAspectWorker
from clue_research.profiling.contact.binding import BindingClassifier, BindingInput
from clue_research.sources import seed_source_manifests
from clue_research.stage0 import load_client_knowledge_pack
from clue_research.synthesis import guard_synthesis_resolution
from clue_research.verification import (
    DEFAULT_BINDING_POLICY,
    DEFAULT_PRE_SPEND_POLICY,
    BindingPolicy,
    PreSpendGateImpl,
    PreSpendPolicy,
    classify_binding,
)

__all__ = [
    "RESEARCH_PACK_LOADERS",
    "VERIFICATION_GATE_ORDER",
    "load_research_packs",
    "VerificationBindingClassifier",
    "production_binding_classifier",
    "build_pre_spend_gate",
    "build_profiling_workers",
    "register_profiling_workers",
    "build_worker_registry",
    "build_research_graph",
]


# --- packs + source manifests ------------------------------------------------

PackLoader = Callable[[AsyncConnection], Awaitable[None]]

# The ordered field-pack loaders a deep run registers — a *registry list*, not a hand-edited call
# sequence (phase-3 pre-flight PF-7). Each new milestone appends its loader from its OWN
# ``api/<milestone>_wiring.py`` (e.g. ``RESEARCH_PACK_LOADERS.append(load_synthesis_pack)``), so
# M10 / M11 / M12 never co-edit ``load_research_packs`` — the M2×M3-class collision the pre-flight
# avoids. Source manifests are seeded after all field packs (``yields`` reference registered keys).
RESEARCH_PACK_LOADERS: list[PackLoader] = [
    load_core_pack,  # M1 core pack
    load_deep_profiling_pack,  # M8 account.resonance.* / contact.facet.*
    load_committee_pack,  # M8.3 contact.role_on_committee / contact.persona
    # M5.1 client.* — the client pack must precede ``seed_source_manifests`` because source
    # ``yields`` validate against the field registry (a manifest naming a client.* yield would
    # crash a fresh-DB boot otherwise); mirrors the tests/stage0/conftest.py ordering contract.
    load_client_knowledge_pack,
]

# The frozen order verification gates apply to a claim (phase-3 pre-flight PF-7; Doc D §7). The use
# gate (M10.3) registers LAST — after the M9 accuracy/identity gates: "is it true / is it this
# person?" before "may we use it?". M10's wiring reads this to slot the use gate; do not reorder.
VERIFICATION_GATE_ORDER: tuple[str, ...] = (
    "pre_spend",  # M9.1 — before any spend
    "resolve",  # M4 waterfall — produce claims
    "corroboration",  # M9.2
    "faithfulness",  # M9.3 — tier-4 synthesized claims
    "identity_binding",  # M9.4 — contact claims
    "use_gate",  # M10.3 — appropriateness/use, runs last
)


#: The one advisory-lock key every seeder takes (ledger A2). Any 64-bit constant works; this one
#: is ``crc32("clue.research_pack_seed")`` so a ``pg_locks`` row can be traced back to this line.
RESEARCH_PACK_SEED_LOCK_KEY = 2_794_525_886


async def load_research_packs(conn: AsyncConnection) -> None:
    """Register every field pack + source manifest a deep-profiling run reads (idempotent).

    Iterates :data:`RESEARCH_PACK_LOADERS` (each milestone appends its loader from its own wiring
    module — PF-7), then seeds the M4 source manifests last. Idempotent: ``register_field`` and
    ``register_source`` are read-then-conditional-inserts, so re-loading on an already-seeded
    connection is a no-op.

    **Serialised across processes (ledger A2, 2026-09-12).** Read-then-insert is not safe when two
    workers boot together: both read "absent", both insert, and the loser dies on
    ``field_definition_pkey`` — three of four fleet workers died that way on 2026-09-11. The seed
    therefore takes a transaction-scoped advisory lock first, so concurrent boots queue on it and
    the second seeder finds every row already committed. A transaction lock needs a transaction:
    every caller runs this inside ``transaction()``, and a caller that does not is refused loudly
    rather than handed a lock that releases the moment it is taken.
    """
    if not conn.in_transaction():
        raise RuntimeError(
            "load_research_packs must run inside a transaction: its advisory lock is "
            "transaction-scoped (call it under clue_db.transaction())"
        )
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": RESEARCH_PACK_SEED_LOCK_KEY}
    )
    for loader in RESEARCH_PACK_LOADERS:
        await loader(conn)
    await seed_source_manifests(conn)


# --- the M9.4 binding adapter (born identity_binding == classify_binding verdict) ---


@dataclass(frozen=True)
class _BindingClaimView:
    """The minimal claim-shaped carrier ``verification.classify_binding`` reads, built from a
    *pre-claim* :class:`BindingInput` so the authoritative classifier can run before the facet claim
    exists. ``classify_binding`` reads ONLY ``id`` / ``entity_id`` (the discarded ``Binding`` keys)
    and ``source_url`` / ``evidence_span`` (``handle_matches`` / ``count_identifier_matches``) —
    never ``value_json`` / ``identity_binding`` / tier — so these four fields suffice."""

    id: ClaimId
    entity_id: EntityId
    source_url: str | None
    evidence_span: str | None


class VerificationBindingClassifier:
    """Adapts the authoritative ``verification.classify_binding`` to M8.4's ``BindingClassifier``
    protocol (the deferred-to-integration injection, CLAUDE.md M9.4×M8.4).

    M8.4 must stamp ``identity_binding`` *before* a ``contact.facet.*`` claim is constructed (the
    binding is required at construction and immutable thereafter), and ``classify_binding`` is the
    post-hoc M9 classifier over a built ``Claim``; profiling may not import ``verification`` (worker
    independence), so M8.4 ships a ``DefaultBindingClassifier`` placeholder. Injecting *this* at the
    api root makes a born facet binding the authoritative M9 verdict, not the M8 default — closing
    M9.4 AC4 / CLAUDE.md's deferred stamp. The two agree on the same-name / verified-handle
    fixtures.
    """

    def __init__(self, *, policy: BindingPolicy = DEFAULT_BINDING_POLICY) -> None:
        self._policy = policy

    def classify(self, inp: BindingInput) -> IdentityBinding:
        view = _BindingClaimView(
            id=new_claim_id(),  # only the discarded Binding.claim_id; just needs to be a ClaimId
            entity_id=inp.contact.id,
            source_url=inp.source_url,
            evidence_span=inp.evidence_span,
        )
        binding = classify_binding(
            view,  # type: ignore[arg-type]  # duck-typed: classify_binding reads only the 4 view fields
            inp.contact,
            account_name=inp.account_name,
            account_aliases=inp.account_aliases,
            manifest_prior=inp.manifest_prior,
            policy=self._policy,
        )
        return binding.strength


def production_binding_classifier(
    *, policy: BindingPolicy = DEFAULT_BINDING_POLICY
) -> BindingClassifier:
    """The api-root :class:`BindingClassifier` to inject into M8.4 (the M9 classifier)."""
    return VerificationBindingClassifier(policy=policy)


# --- the M9.1 pre-spend gate -------------------------------------------------


def build_pre_spend_gate(
    *,
    policy: PreSpendPolicy = DEFAULT_PRE_SPEND_POLICY,
    conn_factory: ConnFactory | None = None,
    record_decisions: bool = True,
) -> PreSpendGate:
    """The api-root :class:`~clue_core.verification.PreSpendGate` to inject before spend.

    Records one ``gate_decision`` audit row per ``check`` (so "did this run gate this
    ``(entity, field)`` before spending?" is a query — M9.1 AC6). ``conn_factory`` defaults to the
    gate's own committed ``transaction`` per check; pass a rollback-scoped factory in tests. (Redis
    cross-run lock detection — the optional ``lock_reader`` — is a caller concern: construct
    :class:`PreSpendGateImpl` directly when a live ``redis`` client is available.)
    """
    if conn_factory is None:
        return PreSpendGateImpl(policy=policy, record_decisions=record_decisions)
    return PreSpendGateImpl(
        policy=policy, conn_factory=conn_factory, record_decisions=record_decisions
    )


# --- worker construction + registration --------------------------------------


def build_profiling_workers(
    *,
    gateway: LLMGateway,
    committee_sources: Sequence[CommitteeSource],
    session_factory: ConnFactory = transaction,
    pre_spend_gate: PreSpendGate | None = None,
    binding_classifier: BindingClassifier | None = None,
    synthesis_guard: SynthesisGuard | None = guard_synthesis_resolution,
    role_model: str | None = None,
    recursion_policy: RecursionPolicy | None = None,
    pack_namespaces: Sequence[str] = (),
) -> list[AspectWorker]:
    """Construct the full M8 deep-profiling worker set (both axes), dependencies injected.

    Account axis (M8.1/M8.2) via :func:`account_axis_workers` — the account/core/resonance/pack
    aspect workers. The committee discoverer (``sources`` + ``gateway`` for role inference) and the
    contact profiler (the authoritative ``binding_classifier`` — defaults to
    :func:`production_binding_classifier`). The ``pre_spend_gate`` is threaded into all three axes:
    account field-fill (FIELD), committee people-enumeration (ENUMERATION) + role inference (FIELD),
    and contact facet-fill (FIELD). The ``synthesis_guard`` (M11.3 ``guard_synthesis_resolution``,
    the account-only + Pass-B-only pre-resolution tripwire) is threaded into the account axis.
    ``recursion_policy`` is shared with the graph so the contact facet sub-worker soft cap and the
    graph's ``SpawnGuard`` hard cap agree.
    """
    recursion = recursion_policy or RecursionPolicy()
    binder = binding_classifier or production_binding_classifier()
    workers: list[AspectWorker] = list(
        account_axis_workers(
            pack_namespaces=pack_namespaces,
            session_factory=session_factory,
            gateway=gateway,
            pre_spend_gate=pre_spend_gate,
            synthesis_guard=synthesis_guard,
        )
    )
    workers.append(
        CommitteeAspectWorker(
            session_factory=session_factory,
            sources=committee_sources,
            gateway=gateway,
            role_model=role_model,
            pre_spend_gate=pre_spend_gate,
        )
    )
    workers.append(
        ContactProfileAspectWorker(
            session_factory=session_factory,
            binding_classifier=binder,
            recursion=recursion,
            pre_spend_gate=pre_spend_gate,
        )
    )
    return workers


def register_profiling_workers(
    registry: WorkerRegistry, workers: Sequence[AspectWorker]
) -> WorkerRegistry:
    """Register each worker into ``registry`` keyed on its ``aspect`` (last-write-wins). Returns the
    registry for chaining. The M7 graph dispatches ``ctx.aspect`` → ``registry.get(aspect)``."""
    for worker in workers:
        registry.register(worker)
    return registry


def build_worker_registry(
    *,
    gateway: LLMGateway,
    committee_sources: Sequence[CommitteeSource],
    session_factory: ConnFactory = transaction,
    pre_spend_gate: PreSpendGate | None = None,
    binding_classifier: BindingClassifier | None = None,
    role_model: str | None = None,
    recursion_policy: RecursionPolicy | None = None,
    pack_namespaces: Sequence[str] = (),
) -> WorkerRegistry:
    """Build + register the full deep-profiling worker set into a fresh :class:`WorkerRegistry`."""
    workers = build_profiling_workers(
        gateway=gateway,
        committee_sources=committee_sources,
        session_factory=session_factory,
        pre_spend_gate=pre_spend_gate,
        binding_classifier=binding_classifier,
        role_model=role_model,
        recursion_policy=recursion_policy,
        pack_namespaces=pack_namespaces,
    )
    return register_profiling_workers(WorkerRegistry(), workers)


def build_research_graph(
    *,
    registry: WorkerRegistry,
    recursion_policy: RecursionPolicy | None = None,
    store: object | None = None,
) -> AccountResearchGraph:
    """Build the M7 per-account research graph over a populated worker ``registry``.

    Pass the SAME ``recursion_policy`` used to build the workers so the soft (prompt) and hard
    (``SpawnGuard``) recursion caps agree. ``store`` defaults to the DB-backed run store; tests
    inject a fake.
    """
    return AccountResearchGraph(
        store=store,  # type: ignore[arg-type]  # None → DbAccountRunStore default; a fake in tests
        workers=registry,
        recursion_policy=recursion_policy,
    )
