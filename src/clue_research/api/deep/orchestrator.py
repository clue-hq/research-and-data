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

**Out of scope (later M8A issues):** the exactly-once spend transaction + the concurrent-admit
reservation (M8A.4), the ``CampaignPhase.DEEP`` handler + high-tier resolution (M8A.2), the handoff
skeleton (M8A.5), and injecting the concrete gate/classifier (M8A.6). The
committee/contact pre-spend gate is **not** wired here: those callables do not yet accept a gate on
this base (that seam lands with #1 at the M8A.6 composition root) — only ``profile_account`` gates.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from clue_research.api.deep.run_io import AccountRunIO
from clue_research.config import DeepPhaseConfig, RecursionPolicy
from clue_research.core import (
    BudgetEngine,
    BudgetScope,
    BudgetVerdict,
    CampaignRunId,
    ClaimId,
    CostCents,
    EntityId,
    ICPSpec,
    LLMGateway,
    PreSpendGate,
    RunId,
    WorkerStatus,
)
from clue_research.durable import AccountRunStatus, AccountRunSubPhase, AccountSpec
from clue_research.profiling import (
    AccountProfileResult,
    CommitteeResult,
    CommitteeSource,
    ContactProfileResult,
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
from clue_research.profiling.runtime import SessionFactory

# The injected worker callables — typed by their *return* so a fake just returns the right result
# shape; each worker's full kwarg signature is checked at M8A.6 + integration, not here, so
# the orchestrator stays decoupled from every worker's internals (it composes, never re-implements).
ProfileAccountFn = Callable[..., Awaitable[AccountProfileResult]]
DiscoverCommitteeFn = Callable[..., Awaitable[CommitteeResult]]
ProfileContactFn = Callable[..., Awaitable[ContactProfileResult]]

# A fixed namespace so ``account_run_id = uuid5(namespace, "campaign:entity")`` is STABLE across a
# crash-and-resume: the same ``(campaign_run, account)`` always maps to one run id, so the M8A.0
# ``sub_phase`` marker and every stage's claim provenance line up on re-entry (the per-account
# analogue of the M7 graph reusing its ``thread_id``). Derived from a name — not a magic literal.
_DEEP_RUN_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "deep-orchestration.clue-research")

# The ``references_index`` key under which the admitted committee member contact-ids are persisted —
# the contact fan-out's resume work-list (ids only, never claim bodies).
_COMMITTEE_CONTACTS_KEY = "committee_contacts"


def deep_account_run_id(campaign_run_id: CampaignRunId, entity_id: EntityId) -> RunId:
    """The deterministic ``account_run`` id for one account in one campaign run (M8A.1).

    Deterministic (``uuid5``) so a resumed phase re-derives the SAME id and resumes the existing
    row rather than minting a fresh one — the per-account analogue of the M7 graph reusing its
    ``thread_id``. This id is the ``claim.run_id`` every stage stamps, so all three stages share one
    provenance line."""
    return RunId(uuid.uuid5(_DEEP_RUN_NAMESPACE, f"{campaign_run_id}:{entity_id}"))


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


class AccountDeepOrchestrator:
    """Sequences ``profile_account → discover_committee → bounded profile_contact fan-out`` for one
    account, advancing the M8A.0 ``sub_phase`` marker and resuming at the last completed boundary.

    Construct once per campaign (the ICP spec + collaborators are campaign-scoped); call
    :meth:`run_one` per account — it is the ``run_one`` callback the M8A.0 scheduler runs inside its
    semaphore + entity-lock slot. All *behavior* is injected (the three worker callables, the run-IO
    cursor, the M7.5 budget engine that admits the per-contact fan-out); only types + the workers'
    inert default-arg sentinels are imported, never a worker body — so the sequencing logic is
    unit-testable with fakes (no DB)."""

    def __init__(
        self,
        *,
        profile_account: ProfileAccountFn,
        discover_committee: DiscoverCommitteeFn,
        profile_contact: ProfileContactFn,
        io: AccountRunIO,
        session_factory: SessionFactory,
        spec: ICPSpec,
        config: DeepPhaseConfig,
        budget: BudgetEngine,
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
        self._budget_cap_cents = budget_cap_cents

    async def run_one(
        self, spec: AccountSpec, *, campaign_run_id: CampaignRunId
    ) -> AccountDeepResult:
        """Deep-orchestrate one account: the three stages in order, resuming at ``sub_phase``.

        Idempotent on re-entry — completed stages are skipped (a contact never profiled before the
        committee admits it; the committee is a hard gate before the fan-out)."""
        run_id = deep_account_run_id(campaign_run_id, spec.entity_id)
        tenant_id = spec.tenant_id or self._spec.client_id

        await self._io.ensure(
            account_run_id=run_id,
            campaign_run_id=campaign_run_id,
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

        # --- Stage 1: account axis (M8.1) — the direct callable carries the ICP spec + tenant_id as
        # explicit kwargs (no AspectContext / ctx.params), so the planner loads the spec and the
        # tenant-private resonance writes bind their tenant without the "#2" graph param-threading.
        if done is None:
            account_result = await self._profile_account(
                account_entity_id=spec.entity_id,
                spec=self._spec,
                tier=spec.tier,
                run_id=run_id,
                campaign_run_id=campaign_run_id,
                tenant_id=tenant_id,
                budget_cap_cents=self._budget_cap_cents,
                recursion_policy=self._recursion_policy,
                gateway=self._gateway,
                planner_model=self._planner_model,
                pre_spend_gate=self._pre_spend_gate,
            )
            cost += account_result.cost_cents
            if account_result.status is WorkerStatus.FAILED and not account_result.aspects:
                # The account did not resolve (``profile_account`` returns FAILED with no aspects
                # when the entity is absent). Committee/contact have no account to target and would
                # raise mid-stage, so stop here — a clean hard-stop the M8A.2 handler records as a
                # FAILED account — rather than advance the marker and crash in stage 2. The marker
                # stays un-advanced so the run is honestly "not started" (a no-op on a retry).
                return AccountDeepResult(
                    account_run_id=run_id,
                    entity_id=spec.entity_id,
                    tier=spec.tier,
                    account=account_result,
                    cost_cents=cost,
                    sub_phase=done,
                )
            refs["account"] = [str(c) for c in account_result.claim_refs]
            await self._io.save(
                run_id,
                references_index=refs,
                cost_cents=cost,
                status=AccountRunStatus.RUNNING,
                sub_phase=AccountRunSubPhase.ACCOUNT_PROFILED,
            )
            done = AccountRunSubPhase.ACCOUNT_PROFILED

        # --- Stage 2: committee axis (M8.3) — direct callable (no AspectContext, so the ctx.params
        # KeyError hazard never arises). Persist the admitted member contact-ids so the contact
        # fan-out resumes WITHOUT re-discovering the committee.
        if done is AccountRunSubPhase.ACCOUNT_PROFILED:
            async with self._session_factory() as conn:
                committee_result = await self._discover_committee(
                    conn,
                    account_entity_id=spec.entity_id,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    sources=self._sources,
                    gateway=self._gateway,
                    spec=self._spec,
                    role_model=self._role_model,
                    budget_cap_cents=self._budget_cap_cents,
                    config=self._committee_config,
                )
            cost += committee_result.cost_cents
            refs["committee"] = [str(c) for c in committee_result.claim_refs]
            refs[_COMMITTEE_CONTACTS_KEY] = [
                str(m.contact_entity_id) for m in committee_result.members
            ]
            await self._io.save(
                run_id,
                references_index=refs,
                cost_cents=cost,
                status=AccountRunStatus.RUNNING,
                sub_phase=AccountRunSubPhase.COMMITTEE_DISCOVERED,
            )
            done = AccountRunSubPhase.COMMITTEE_DISCOVERED

        # --- Stage 3: contact axis (M8.4) — bounded fan-out over the admitted members (M8A.3): the
        # level-1 breadth is capped at committee_size_cap, each contact is budget-admitted at the
        # chokepoint, and the intra-account semaphore caps concurrency. ``budget_stop`` records the
        # verdict (if any) that halted admission.
        if done is AccountRunSubPhase.COMMITTEE_DISCOVERED:
            contact_ids = self._committee_contact_ids(committee_result, refs)
            contact_results, budget_stop = await self._profile_contacts(
                contact_ids[: self._config.committee_size_cap],
                campaign_run_id=campaign_run_id,
                account_entity_id=spec.entity_id,
                run_id=run_id,
                tenant_id=tenant_id,
                tier=spec.tier,
            )
            for contact in contact_results:
                cost += contact.cost_cents
                refs[f"contact:{contact.contact_entity_id}"] = [str(c) for c in contact.claim_refs]
            # The contact axis is complete even when budget halted admission: a ``DENY`` exhausted
            # the account envelope and a ``GRACEFUL_STOP`` "finishes the in-flight unit and stops at
            # the next checkpoint" — both leave this account a *finished partial* (coverage-
            # confidence, not completeness), so the marker advances and the run is DONE. The
            # ``budget_stop`` verdict (surfaced on the result) is what the handler reads to suspend
            # the *phase* (GRACEFUL_STOP) or continue the batch with partial coverage (DENY).
            await self._io.save(
                run_id,
                references_index=refs,
                cost_cents=cost,
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
        campaign_run_id: CampaignRunId,
        account_entity_id: EntityId,
        run_id: RunId,
        tenant_id: str,
        tier: str,
    ) -> tuple[tuple[ContactProfileResult, ...], BudgetVerdict | None]:
        """Admit-then-launch the contact fan-out under the four fan-out bounds (M8A.3, Doc C §3/§5).

        Before each member, ask the cost dial whether the account can afford one more contact —
        ``BudgetEngine.check(scope=ACCOUNT)`` projecting ``per_contact_estimate_cents`` — and launch
        only an ``ALLOW``. The verdict at the chokepoint:

        * ``ALLOW`` — schedule the profile under the ``max_contacts_in_flight`` semaphore.
        * ``DENY`` — the account's envelope is spent; stop admitting and return what was admitted
          as a **partial committee** (coverage-confidence, not completeness, Doc C §3) — not failed.
        * ``GRACEFUL_STOP`` — a run-level cap is breached; finish the admitted in-flight contacts
          and surface the verdict so the handler (M8A.2) suspends the phase at the next checkpoint.

        Returns ``(results, budget_stop)`` where ``budget_stop`` is the verdict that halted
        admission (``None`` if every in-cap member was admitted). The four bounds all live at this
        one chokepoint: (a) committee-size truncation (the caller slices ``contact_ids``), (b) this
        ``check`` admission, (c) the contact worker's per-tier ``facet_subworker_budget``, (d) the
        in-flight semaphore — none of them hardcoded; (a)/(b)/(c)/(d) all read from
        :class:`DeepPhaseConfig` / :class:`RecursionPolicy`.

        Note: the sequential admit reads spend-so-far while already-launched peers have not yet
        ``record``-ed, so concurrent admits can collectively overshoot the per-account cap by a
        bounded window. Closing that window (a reservation) and the exactly-once charge are
        **M8A.4**; this method only opens the admission seam.
        """
        semaphore = asyncio.Semaphore(self._config.max_contacts_in_flight)
        facet_budget = (
            self._recursion_policy.caps_for(tier).max_facet_workers_per_aspect
            if self._recursion_policy is not None
            else 0
        )

        async def _one(contact_id: EntityId) -> ContactProfileResult:
            async with semaphore, self._session_factory() as conn:
                return await self._profile_contact(
                    conn,
                    contact_entity_id=contact_id,
                    account_entity_id=account_entity_id,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    tier=tier,
                    spec=self._spec,
                    facet_subworker_budget=facet_budget,
                    binding_classifier=self._binding_classifier,
                    use_class_tagger=self._use_class_tagger,
                    config=self._contact_config,
                )

        tasks: list[asyncio.Task[ContactProfileResult]] = []
        budget_stop: BudgetVerdict | None = None
        try:
            for contact_id in contact_ids:
                decision = await self._budget.check(
                    scope=BudgetScope.ACCOUNT,
                    projected_cents=self._config.per_contact_estimate_cents,
                    campaign_run_id=campaign_run_id,
                    entity_id=account_entity_id,
                    account_run_id=run_id,
                )
                if decision.verdict is BudgetVerdict.ALLOW:
                    tasks.append(asyncio.create_task(_one(contact_id)))
                else:
                    # DENY (partial) or GRACEFUL_STOP (pause): stop admitting; the already-launched
                    # contacts below still finish (GRACEFUL_STOP = "finish the in-flight unit").
                    budget_stop = decision.verdict
                    break
            return tuple(await asyncio.gather(*tasks)), budget_stop
        except BaseException:
            # Never leave an admitted contact detached. ``create_task`` schedules eagerly, so if
            # admission itself raises (e.g. ``budget.check`` hits a DB error) — or one ``_one``
            # raises in the gather, which does NOT cancel its in-flight siblings — cancel every
            # launched task and drain it before propagating. The M8A.2 handler marks the account
            # FAILED; claims already committed are idempotent on resume, so cancelling in-flight
            # work is safe (and stops wasted spend). This also forwards a cancellation of
            # ``_profile_contacts`` itself to its children.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
