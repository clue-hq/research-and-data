"""The per-account deep-orchestration sequence (M8A.1) — ``account → committee → contact``.

The trunk of M8A: for ONE high-tier account, run the three M8 worker families in the right order,
checkpoint the boundary, and bound the per-contact fan-out — the seam no single milestone owned (M8
built the workers, M7 the substrate, but nothing sequenced them). It is **pure composition with
injected collaborators**: it sequences the three *direct callables* (``profile_account`` /
``discover_committee`` / ``profile_contact``), so the ``ctx.params`` KeyError hazard of dispatching
committee/contact through the M7 graph never arises and the account axis carries the ICP spec +
tenant as explicit kwargs (designing out the "#2" graph param-threading on this path).

Shaped to be the ``run_one`` callback the M8A.0 ``AccountScheduler`` runs inside its
bounded-parallelism + per-entity single-flight slot, so a whole campaign's accounts deep-
research under the scheduler's caps with the three-stage sequence per account.

Resumable on the M8A.0 ``account_run.sub_phase`` marker: a crash resumes at the last completed
boundary — never re-profiling the account or re-discovering the committee. The contact fan-out's
work-list (the admitted member ids) is persisted with the committee boundary, so the fan-out resumes
without re-running discovery; the gap-recompute (a re-profiled contact's FRESH fields are
skipped) is the correctness backstop, so a double-entered stage converges to a no-op.

The per-contact fan-out is bounded by the four fan-out bounds at one chokepoint (M8A.3, Doc C
§3/§5): committee-size truncation, the ``BudgetEngine.check(scope=ACCOUNT)`` admission gate before
each contact, the contact worker's per-tier facet sub-worker budget, and the intra-account in-flight
semaphore. A budget ``DENY`` yields a partial committee (coverage-confidence, not completeness); a
``GRACEFUL_STOP`` is surfaced so the handler suspends the phase.

**Exactly-once spend (M8A.4).** Each stage's spend runs through the injected
:class:`~clue_api.deep.spend.ExactlyOnceSpend`. For the **committee and contact** axes the
worker's claim write(s), the :meth:`~clue_research.durable.budget.BudgetEngine.record` charge, and
the M7.4 ledger ``succeed`` all commit on **one** connection — so a crash never leaves the client
hard-cap counter desynced from those claims (no under-count, no double-charge). The **account** axis
is ledger-anchored only: ``profile_account`` writes its account/resonance claims in its own
transactions, so a crash before its charge commits under-counts the account portion and re-runs
``profile_account`` on resume (its M7-graph idempotency + the gap-recompute are the backstop; spec
§M8A.4 scopes that out). ``record`` is the single live writer of the per-account spend (the
references-fold no longer writes ``cost_cents``). On resume the contact fan-out recovers
already-charged contacts' references straight from the durable ledger (so a cap-saturated resume
cannot drop them), and the admission carries a local reservation so concurrent admits cannot
collectively breach the per-account cap.

**Pre-spend gate (M8A.6 / #1).** The injected ``pre_spend_gate`` is threaded into **all three**
axes — ``profile_account`` (account field-fill), ``discover_committee`` (people-enumeration +
role inference), and ``profile_contact`` (facet-fill) — so every claim-producing path on this
sequence consults the gate before it spends (the deferred M9.1 routing, closed at the composition
root; ``None`` here means an un-wired unit-test orchestrator, which is gate-free by design).

**Out of scope (later M8A issues):** constructing + injecting the concrete gate/classifier and the
high-tier resolution live at the M8A.6 composition root (``api/deep/composition.py``); this trunk
only *threads* whatever collaborators it is handed.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from clue_api.deep.run_io import AccountRunIO
from clue_api.deep.spend import (
    ExactlyOnceSpend,
    StepInfo,
    already_done,
    deep_step_key,
)
from clue_config import DeepPhaseConfig, RecursionPolicy
from clue_core import (
    BudgetEngine,
    BudgetScope,
    BudgetVerdict,
    ClaimId,
    CostCents,
    EntityId,
    ICPSpec,
    LLMGateway,
    PreSpendGate,
    ProjectRunId,
    RunId,
    WorkerStatus,
)
from clue_db import ConnFactory
from clue_research.durable import AccountRunStatus, AccountRunSubPhase, AccountSpec
from clue_research.profiling import (
    AccountProfileResult,
    CommitteeResult,
    CommitteeSource,
    ContactProfileResult,
    SynthesisGuard,
)
from clue_research.profiling.committee import DEFAULT_COMMITTEE_CONFIG, CommitteeConfig
from clue_research.profiling.contact import (
    DEFAULT_BINDING_CLASSIFIER,
    DEFAULT_CONTACT_PROFILE_CONFIG,
    DEFAULT_USE_CLASS_TAGGER,
    BindingClassifier,
    ContactProfileConfig,
    UseClassTagger,
)

# The injected worker callables — typed by their *return* so a fake just returns the right result
# shape; each worker's full kwarg signature is checked at M8A.6 + integration, not here, so
# the orchestrator stays decoupled from every worker's internals (it composes, never re-implements).
ProfileAccountFn = Callable[..., Awaitable[AccountProfileResult]]
DiscoverCommitteeFn = Callable[..., Awaitable[CommitteeResult]]
ProfileContactFn = Callable[..., Awaitable[ContactProfileResult]]

# A fixed namespace so ``account_run_id = uuid5(namespace, "campaign:entity")`` is STABLE across a
# crash-and-resume: the same ``(project_run, account)`` always maps to one run id, so the M8A.0
# ``sub_phase`` marker and every stage's claim provenance line up on re-entry (the per-account
# analogue of the M7 graph reusing its ``thread_id``). Derived from a name — not a magic literal.
_DEEP_RUN_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "deep-orchestration.clue-research")

# The ``references_index`` key under which the admitted committee member contact-ids are persisted —
# the contact fan-out's resume work-list (ids only, never claim bodies).
_COMMITTEE_CONTACTS_KEY = "committee_contacts"


def deep_account_run_id(project_run_id: ProjectRunId, entity_id: EntityId) -> RunId:
    """The deterministic ``account_run`` id for one account in one campaign run (M8A.1).

    Deterministic (``uuid5``) so a resumed phase re-derives the SAME id and resumes the existing
    row rather than minting a fresh one — the per-account analogue of the M7 graph reusing its
    ``thread_id``. This id is the ``claim.run_id`` every stage stamps, so all three stages share one
    provenance line."""
    return RunId(uuid.uuid5(_DEEP_RUN_NAMESPACE, f"{project_run_id}:{entity_id}"))


class AccountDeepResult(BaseModel):
    """The references-only outcome of deep-orchestrating ONE account (M8A.1).

    Carries the three stage results (so M8A.5 can key the handoff skeleton) + the run's cost +
    its final ``sub_phase``; :attr:`claim_refs` flattens every claim id written across the stages. A
    *resumed* run leaves the skipped stages' results ``None`` — they already live in the claim store
    keyed by this run id, and were not re-run.

    :attr:`budget_stop` records the verdict that halted the contact fan-out's admission (M8A.3), or
    ``None`` if every in-cap member was admitted: a ``DENY`` means the account's envelope was spent
    (a *partial* committee — coverage-confidence, not completeness), a ``GRACEFUL_STOP`` means a
    run-level cap was breached. The M8A.2 handler reads it to suspend the phase (``GRACEFUL_STOP`` →
    ``PhaseResult(PAUSED)``) or continue the batch with partial coverage (``DENY``); either way the
    account is **partial, never FAILED**."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_run_id: RunId
    entity_id: EntityId
    tier: str
    account: AccountProfileResult | None = None
    committee: CommitteeResult | None = None
    contacts: tuple[ContactProfileResult, ...] = ()
    cost_cents: CostCents = Decimal(0)
    sub_phase: AccountRunSubPhase | None = None
    budget_stop: BudgetVerdict | None = None

    @property
    def claim_refs(self) -> tuple[ClaimId, ...]:
        """Every claim id written this run, flattened across stages (references only)."""
        refs: list[ClaimId] = []
        if self.account is not None:
            refs.extend(self.account.claim_refs)
        if self.committee is not None:
            refs.extend(self.committee.claim_refs)
        for contact in self.contacts:
            refs.extend(contact.claim_refs)
        return tuple(refs)


@dataclass(frozen=True, slots=True)
class _ContactOutcome:
    """One contact's exactly-once spend outcome (M8A.4): the contact id, the worker result (``None``
    on a ``REPLAY`` — a resumed fan-out recovers the references from the ledger, not a re-run), and
    the references-only :class:`~clue_api.deep.spend.StepInfo` (claim ids + cost + the
    ``replayed`` flag the orchestrator reads to avoid double-counting an already-booked charge)."""

    contact_entity_id: EntityId
    result: ContactProfileResult | None
    info: StepInfo


@dataclass(slots=True)
class _Reservation:
    """In-memory per-account spend reservation (M8A.4) for the concurrent contact fan-out.

    ``BudgetEngine.check`` reads only the committed ``account_run.cost_cents``, so under concurrency
    it cannot see peers already admitted-but-not-yet-charged → N concurrent admits could
    collectively breach the per-account cap. This tracks both halves: ``committed`` is the account's
    charged spend so far (account + committee + each settled contact) and ``reserved`` the estimate
    of every admitted-not-yet-charged contact. The admission guard tests ``committed + reserved +
    estimate`` against the cap. Single-threaded asyncio → the mutations are safe at await boundaries
    (the admission loop and the contact tasks interleave only where they ``await``)."""

    committed: CostCents
    reserved: CostCents = Decimal(0)

    def reserve(self, estimate: CostCents) -> None:
        """Reserve one contact's estimate at admit (decrement-at-admit)."""
        self.reserved += estimate

    def settle(self, estimate: CostCents, actual: CostCents) -> None:
        """Convert a reservation to the real (or zero, on REPLAY) charge once it commits."""
        self.reserved -= estimate
        self.committed += actual

    def outstanding(self, estimate: CostCents) -> CostCents:
        """What the account would owe if one more contact (``estimate``) were admitted now."""
        return self.committed + self.reserved + estimate


class AccountDeepOrchestrator:
    """Sequences ``profile_account → discover_committee → bounded profile_contact fan-out`` for one
    account, advancing the M8A.0 ``sub_phase`` marker and resuming at the last completed boundary.

    Construct once per campaign (the ICP spec + collaborators are campaign-scoped); call
    :meth:`run_one` per account — it is the ``run_one`` callback the M8A.0 scheduler runs inside its
    semaphore + entity-lock slot. All *behavior* is injected (the three worker callables, the run-IO
    cursor, the M7.5 budget engine that admits the per-contact fan-out, and the M8A.4
    :class:`~clue_api.deep.spend.ExactlyOnceSpend` that commits each stage's claim writes +
    charge + ledger in one transaction); only types + the workers' inert default-arg sentinels are
    imported, never a worker body — so the sequencing logic is unit-testable with fakes (no DB)."""

    def __init__(
        self,
        *,
        profile_account: ProfileAccountFn,
        discover_committee: DiscoverCommitteeFn,
        profile_contact: ProfileContactFn,
        io: AccountRunIO,
        session_factory: ConnFactory,
        spec: ICPSpec,
        config: DeepPhaseConfig,
        budget: BudgetEngine,
        spend: ExactlyOnceSpend,
        sources: Sequence[CommitteeSource],
        gateway: LLMGateway,
        role_model: str | None = None,
        committee_config: CommitteeConfig = DEFAULT_COMMITTEE_CONFIG,
        contact_config: ContactProfileConfig = DEFAULT_CONTACT_PROFILE_CONFIG,
        binding_classifier: BindingClassifier = DEFAULT_BINDING_CLASSIFIER,
        use_class_tagger: UseClassTagger = DEFAULT_USE_CLASS_TAGGER,
        recursion_policy: RecursionPolicy | None = None,
        planner_model: str | None = None,
        pre_spend_gate: PreSpendGate | None = None,
        synthesis_guard: SynthesisGuard | None = None,
        budget_cap_cents: CostCents | None = None,
    ) -> None:
        self._profile_account = profile_account
        self._discover_committee = discover_committee
        self._profile_contact = profile_contact
        self._io = io
        self._session_factory = session_factory
        self._spec = spec
        self._config = config
        self._budget = budget
        self._spend = spend
        self._sources = tuple(sources)
        self._gateway = gateway
        self._role_model = role_model
        self._committee_config = committee_config
        self._contact_config = contact_config
        self._binding_classifier = binding_classifier
        self._use_class_tagger = use_class_tagger
        self._recursion_policy = recursion_policy
        self._planner_model = planner_model
        self._pre_spend_gate = pre_spend_gate
        self._synthesis_guard = synthesis_guard
        self._budget_cap_cents = budget_cap_cents

    async def run_one(
        self, spec: AccountSpec, *, project_run_id: ProjectRunId
    ) -> AccountDeepResult:
        """Deep-orchestrate one account: the three stages in order, resuming at ``sub_phase``.

        Idempotent on re-entry — completed stages are skipped (a contact never profiled before the
        committee admits it; the committee is a hard gate before the fan-out)."""
        run_id = deep_account_run_id(project_run_id, spec.entity_id)
        workspace_id = spec.workspace_id or self._spec.workspace_id

        await self._io.ensure(
            account_run_id=run_id,
            project_run_id=project_run_id,
            entity_id=spec.entity_id,
            tier=spec.tier,
        )
        state = await self._io.load(run_id)
        refs: dict[str, list[str]] = {k: list(v) for k, v in state.references_index.items()}
        cost = state.cost_cents
        done = state.sub_phase

        account_result: AccountProfileResult | None = None
        committee_result: CommitteeResult | None = None
        contact_results: tuple[ContactProfileResult, ...] = ()
        budget_stop: BudgetVerdict | None = None

        # --- Stage 1: account axis (M8.1) — the direct callable carries the ICP spec +
        # workspace_id as
        # explicit kwargs (no AspectContext / ctx.params), so the planner loads the spec and the
        # tenant-private resonance writes bind their tenant without the "#2" graph param-threading.
        if done is None:
            account_result = await self._profile_account(
                account_entity_id=spec.entity_id,
                spec=self._spec,
                tier=spec.tier,
                run_id=run_id,
                project_run_id=project_run_id,
                workspace_id=workspace_id,
                budget_cap_cents=self._budget_cap_cents,
                recursion_policy=self._recursion_policy,
                gateway=self._gateway,
                planner_model=self._planner_model,
                pre_spend_gate=self._pre_spend_gate,
                synthesis_guard=self._synthesis_guard,
            )
            if account_result.status is WorkerStatus.FAILED and not account_result.aspects:
                # The account did not resolve (``profile_account`` returns FAILED with no aspects
                # when the entity is absent, cost 0). Committee/contact have no account to target,
                # so stop here — a clean hard-stop the M8A.2 handler marks FAILED, without spending
                # or advancing the marker (a no-op on a retry).
                return AccountDeepResult(
                    account_run_id=run_id,
                    entity_id=spec.entity_id,
                    tier=spec.tier,
                    account=account_result,
                    cost_cents=cost,
                    sub_phase=done,
                )
            # The account/resonance claims already committed in ``profile_account``'s own
            # transactions (it opens its own sessions). Record its charge + a ledger anchor and fold
            # the references + marker in ONE transaction (M8A.4): the account-axis *claim-write*
            # atomicity stays the M7 graph's domain, but its cost now flows through ``record`` (the
            # single ``cost_cents`` writer) and the ledger guards a double-record on resume.
            async with self._session_factory() as conn:
                _, info = await self._spend.run_step(
                    conn,
                    key=deep_step_key(run_id, "account"),
                    project_run_id=project_run_id,
                    account_run_id=run_id,
                    entity_id=spec.entity_id,
                    work=already_done(account_result),
                )
                refs["account"] = list(info.claim_ids)
                await self._io.fold(
                    conn,
                    run_id,
                    references_index=refs,
                    status=AccountRunStatus.RUNNING,
                    sub_phase=AccountRunSubPhase.ACCOUNT_PROFILED,
                )
            if not info.replayed:
                cost += info.cost_cents
            done = AccountRunSubPhase.ACCOUNT_PROFILED

        # --- Stage 2: committee axis (M8.3) — direct callable (no AspectContext, so the ctx.params
        # KeyError hazard never arises). The committee's claim writes, its charge, the ledger
        # ``succeed``, the member-id work-list, and the marker all commit in one transaction (M8A.4)
        # so the contact fan-out resumes WITHOUT re-discovering the committee and the work-list is
        # never lost vs the ledger.
        if done is AccountRunSubPhase.ACCOUNT_PROFILED:
            async with self._session_factory() as conn:
                committee_result, info = await self._spend.run_step(
                    conn,
                    key=deep_step_key(run_id, "committee"),
                    project_run_id=project_run_id,
                    account_run_id=run_id,
                    entity_id=spec.entity_id,
                    work=lambda c: self._discover_committee(
                        c,
                        account_entity_id=spec.entity_id,
                        run_id=run_id,
                        workspace_id=workspace_id,
                        sources=self._sources,
                        gateway=self._gateway,
                        spec=self._spec,
                        role_model=self._role_model,
                        budget_cap_cents=self._budget_cap_cents,
                        pre_spend_gate=self._pre_spend_gate,
                        config=self._committee_config,
                    ),
                )
                refs["committee"] = list(info.claim_ids)
                if committee_result is not None:  # EXECUTE — refresh the work-list from the members
                    refs[_COMMITTEE_CONTACTS_KEY] = [
                        str(m.contact_entity_id) for m in committee_result.members
                    ]
                await self._io.fold(
                    conn,
                    run_id,
                    references_index=refs,
                    status=AccountRunStatus.RUNNING,
                    sub_phase=AccountRunSubPhase.COMMITTEE_DISCOVERED,
                )
            if not info.replayed:
                cost += info.cost_cents
            done = AccountRunSubPhase.COMMITTEE_DISCOVERED

        # --- Stage 3: contact axis (M8.4) — bounded fan-out over the admitted members (M8A.3): the
        # level-1 breadth is capped at committee_size_cap, each contact is budget-admitted (with the
        # M8A.4 concurrent-admit reservation), and the intra-account semaphore caps concurrency;
        # contact's claim writes + charge + ledger ``succeed`` commit in ONE transaction (M8A.4);
        # ``budget_stop`` records the verdict (if any) that halted admission.
        if done is AccountRunSubPhase.COMMITTEE_DISCOVERED:
            contact_ids = self._committee_contact_ids(committee_result, refs)
            outcomes, budget_stop = await self._profile_contacts(
                contact_ids[: self._config.committee_size_cap],
                project_run_id=project_run_id,
                account_entity_id=spec.entity_id,
                run_id=run_id,
                workspace_id=workspace_id,
                tier=spec.tier,
                committed_cents=cost,
            )
            for outcome in outcomes:
                if not outcome.info.replayed:
                    cost += outcome.info.cost_cents
                refs[f"contact:{outcome.contact_entity_id}"] = list(outcome.info.claim_ids)
            contact_results = tuple(o.result for o in outcomes if o.result is not None)
            # The contact axis is complete even when budget halted admission: a ``DENY`` exhausted
            # the account envelope and a ``GRACEFUL_STOP`` "finishes the in-flight unit and stops at
            # the next checkpoint" — both leave this account a *finished partial* (coverage-
            # confidence, not completeness), so the marker advances and the run is DONE. The
            # ``budget_stop`` verdict (surfaced on the result) is what the handler reads to suspend
            # the *phase* (GRACEFUL_STOP) or continue the batch with partial coverage (DENY). Each
            # contact's spend already committed atomically; this fold records the references +
            # marker (contact claim ids are recovered from each ledger row on a resumed fan-out).
            async with self._session_factory() as conn:
                await self._io.fold(
                    conn,
                    run_id,
                    references_index=refs,
                    status=AccountRunStatus.DONE,
                    sub_phase=AccountRunSubPhase.CONTACTS_COMPLETE,
                )
            done = AccountRunSubPhase.CONTACTS_COMPLETE

        return AccountDeepResult(
            account_run_id=run_id,
            entity_id=spec.entity_id,
            tier=spec.tier,
            account=account_result,
            committee=committee_result,
            contacts=contact_results,
            cost_cents=cost,
            sub_phase=done,
            budget_stop=budget_stop,
        )

    def _committee_contact_ids(
        self, committee: CommitteeResult | None, refs: dict[str, list[str]]
    ) -> tuple[EntityId, ...]:
        """The contact fan-out work-list: the just-discovered members on a fresh run, else the
        contact-ids persisted under ``committee_contacts`` — so a resume never re-discovers."""
        if committee is not None:
            return tuple(member.contact_entity_id for member in committee.members)
        return tuple(EntityId(uuid.UUID(cid)) for cid in refs.get(_COMMITTEE_CONTACTS_KEY, ()))

    async def _profile_contacts(
        self,
        contact_ids: Sequence[EntityId],
        *,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
        run_id: RunId,
        workspace_id: str,
        tier: str,
        committed_cents: CostCents,
    ) -> tuple[tuple[_ContactOutcome, ...], BudgetVerdict | None]:
        """Admit-then-launch the contact fan-out under the four fan-out bounds (M8A.3, Doc C §3/§5)
        with exactly-once spend + a concurrent-admit reservation (M8A.4).

        Before each member, ask the cost dial whether the account can afford one more contact —
        ``BudgetEngine.check(scope=ACCOUNT)`` projecting ``per_contact_estimate_cents`` — and launch
        only an ``ALLOW`` that also clears the reservation guard. The verdict at the chokepoint:

        * ``ALLOW`` (+ within the reservation) — schedule the profile under the
          ``max_contacts_in_flight`` semaphore; each runs as one exactly-once spend step (claim +
          claim-writes + charge + ledger ``succeed`` in one transaction).
        * ``DENY`` — the account's envelope is spent; stop admitting and return what was admitted
          as a **partial committee** (coverage-confidence, not completeness, Doc C §3) — not failed.
        * ``GRACEFUL_STOP`` — a run-level cap is breached; finish the admitted in-flight contacts
          and surface the verdict so the handler (M8A.2) suspends the phase at the next checkpoint.

        Returns ``(outcomes, budget_stop)`` where each :class:`_ContactOutcome` carries the result
        (``None`` on a recovered/replayed contact) + references-only step info, and ``budget_stop``
        the verdict that halted admission (``None`` if every in-cap member was admitted). The four
        bounds all live at this one chokepoint: (a) committee-size truncation (the caller slices
        ``contact_ids``), (b) this ``check`` admission, (c) the contact worker's per-tier
        ``facet_subworker_budget``, (d) the in-flight semaphore — none hardcoded; all read from
        :class:`DeepPhaseConfig` / :class:`RecursionPolicy`.

        **Resume recovery (M8A.4).** A contact already charged on a prior run (its ledger row is
        ``SUCCEEDED``) is recovered **directly from the durable ledger** — its references folded, no
        re-spend — *independent of the budget gate*, before any admission. This is the
        crux of resume safety: when every contact was already charged the account is **at** its cap,
        so the admission ``check`` would ``DENY`` re-admission; recovering references through
        re-admission would then silently drop the whole committee's contact claims from
        ``references_index`` (M8A.5/M12 read it). Only un-recorded members go through the admission
        spend. Recovering already-paid contacts here (vs re-admitting them) also keeps the
        reservation honest — a recovered charge is in the committed seed but never reserved, so it
        is not double-counted.

        The **reservation** closes the concurrent over-commit window the bare ``check`` left open:
        ``check`` sees only the committed ``cost_cents``, so launched-but-uncharged peers are
        invisible to it; the local :class:`_Reservation` accounts for them so concurrent admits
        cannot collectively breach the per-account cap (paired with ``max_contacts_in_flight``).
        """
        semaphore = asyncio.Semaphore(self._config.max_contacts_in_flight)
        facet_budget = (
            self._recursion_policy.caps_for(tier).max_facet_workers_per_aspect
            if self._recursion_policy is not None
            else 0
        )
        estimate = self._config.per_contact_estimate_cents

        # --- Resume recovery: fold already-charged contacts from the durable ledger (no re-spend,
        # no budget gate), and admit only the un-recorded members below. ``committed_cents`` already
        # includes the recovered charges (it is the record-owned ``account_run.cost_cents``), so the
        # reservation seeds with it but only reserves for the *pending* members → no double-count.
        recovered: list[_ContactOutcome] = []
        pending: list[EntityId] = []
        async with self._session_factory() as conn:
            for contact_id in contact_ids:
                info = await self._spend.recorded(
                    conn, deep_step_key(run_id, f"contact:{contact_id}")
                )
                if info is not None:
                    recovered.append(
                        _ContactOutcome(contact_entity_id=contact_id, result=None, info=info)
                    )
                else:
                    pending.append(contact_id)

        reservation = _Reservation(committed=committed_cents)

        async def _one(contact_id: EntityId) -> _ContactOutcome:
            async with semaphore, self._session_factory() as conn:
                result, info = await self._spend.run_step(
                    conn,
                    key=deep_step_key(run_id, f"contact:{contact_id}"),
                    project_run_id=project_run_id,
                    account_run_id=run_id,
                    entity_id=account_entity_id,
                    work=lambda c: self._profile_contact(
                        c,
                        contact_entity_id=contact_id,
                        account_entity_id=account_entity_id,
                        run_id=run_id,
                        workspace_id=workspace_id,
                        tier=tier,
                        spec=self._spec,
                        facet_subworker_budget=facet_budget,
                        binding_classifier=self._binding_classifier,
                        use_class_tagger=self._use_class_tagger,
                        pre_spend_gate=self._pre_spend_gate,
                        config=self._contact_config,
                    ),
                )
            # The transaction committed: the reservation becomes the real charge (or zero on a
            # REPLAY, whose charge was already booked on the prior run).
            reservation.settle(estimate, Decimal(0) if info.replayed else info.cost_cents)
            return _ContactOutcome(contact_entity_id=contact_id, result=result, info=info)

        tasks: list[asyncio.Task[_ContactOutcome]] = []
        budget_stop: BudgetVerdict | None = None
        try:
            for contact_id in pending:
                decision = await self._budget.check(
                    scope=BudgetScope.ACCOUNT,
                    projected_cents=estimate,
                    project_run_id=project_run_id,
                    entity_id=account_entity_id,
                    account_run_id=run_id,
                )
                if decision.verdict is not BudgetVerdict.ALLOW:
                    # DENY (partial) or GRACEFUL_STOP (pause): stop admitting; the already-launched
                    # contacts below still finish (GRACEFUL_STOP = "finish the in-flight unit").
                    budget_stop = decision.verdict
                    break
                if (
                    decision.cap_cents > 0
                    and reservation.outstanding(estimate) > decision.cap_cents
                ):
                    # The engine ALLOW-ed against committed spend, but the in-flight reservations of
                    # already-admitted peers would breach the per-account cap → stop admitting (a
                    # partial, like a DENY). ``cap_cents == 0`` means uncapped → the guard is inert.
                    budget_stop = BudgetVerdict.DENY
                    break
                reservation.reserve(estimate)
                tasks.append(asyncio.create_task(_one(contact_id)))
            admitted = tuple(await asyncio.gather(*tasks))
            # Recovered-from-ledger contacts first (their refs are folded regardless of the gate),
            # then the freshly-admitted ones.
            return tuple(recovered) + admitted, budget_stop
        except BaseException:
            # Never leave an admitted contact detached. ``create_task`` schedules eagerly, so if
            # admission itself raises (e.g. ``budget.check`` hits a DB error) — or one ``_one``
            # raises in the gather, which does NOT cancel its in-flight siblings — cancel every
            # launched task and drain it before propagating. The M8A.2 handler marks the account
            # FAILED; claims already committed are idempotent on resume (a crash rolls back the
            # whole spend step), so cancelling in-flight work is safe (and stops wasted spend). This
            # also forwards a cancellation of ``_profile_contacts`` itself to its children.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
