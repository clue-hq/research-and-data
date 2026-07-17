"""The budget caps & cost-governance engine (M7.5) — the single chokepoint for spend authorisation.

The founders' entire cost concern reduces to one dial — *fan-out cost per account × accounts per
pass* — and the architecture demands it be explicit, client-controllable, and **enforced** (Doc C
§5; substrate §5c). :class:`BudgetEngine` is the concrete implementation of the frozen
:class:`clue_core.BudgetEngine` seam: it estimates spend before any deep cost, authorises
(or denies / graceful-stops) every spend through one ``check``, records each charge exactly once,
applies the client-set per-campaign hard cap, and serves the live burn-down the client surface
(M13.4) and the source-intelligence learning loop (M13.3 / Doc C §6) consume.

Three scopes, all real (:class:`~clue_core.BudgetScope`):

* **ACCOUNT** — the per-account deep cap: the account run's per-row override
  (``account_run.budget_cap_cents``) if set, else the per-tier policy band
  (:meth:`~clue_research.config.BudgetCaps.per_account_cap_for`). A breach is a ``DENY`` — the
  M7.2 spawn-denial: the run continues with the aspect marked partial, never a crash.
* **PASS** — the cheap Pass-A per-account ceiling
  (:attr:`~clue_research.config.BudgetCaps.pass_a_cap_cents_per_account`); a runaway scoring cost on
  one account is ``DENY``\\ed. (There is no per-pass *aggregate* spend counter in V1 — Pass A is
  deterministic-only and cheap; this is the per-account-rate guard the spec names.)
* **RUN** — the per-campaign hard cap (``campaign_run.budget_cap_cents``). A breach is a
  ``GRACEFUL_STOP`` — the campaign is brought to a clean stop at the next checkpoint (via M7.3),
  never hard-killed mid-step.

Caps are **policy-as-data** (:class:`~clue_research.config.BudgetCaps`, versioned, per-ICP/client
overridable — already wired into the config loader). Persistence sits behind the
:class:`BudgetStore` seam, so the engine is testable on an in-memory store and the accounting
backend is swappable (Postgres now, Temporal-shaped later) — exactly the conventions §2
replaceability rule the rest of M7 follows.

**Exactly-once charge.** :meth:`record` is the single live increment of the spend counters
(``campaign_run.spent_cents`` + ``account_run.cost_cents``). It is called once per ledger charge —
inside the M7.4 ``idempotent`` EXECUTE branch, *not* on a replay — so the counters tie exactly to
the ledger's ``cost_cents_charged`` (no double-count, no missed charge; substrate §5c). A *charge*
is never a ``budget_event``; events are governance decisions (deny / graceful-stop / breach /
cap-set).
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    BudgetDecision,
    BudgetScope,
    BudgetVerdict,
    BurnDown,
    CampaignRunId,
    CostCents,
    EntityId,
    Estimate,
    RunId,
)
from clue_research.config import BudgetCaps
from clue_research.db import transaction
from clue_research.durable.budget_event import (
    AccountBudgetState,
    RunBudgetState,
    add_account_spend,
    add_run_spend,
    get_account_budget_state,
    get_run_budget_state,
    insert_budget_event,
    set_account_budget_cap,
    set_estimated_cents,
)
from clue_research.durable.campaign_run import set_budget_cap
from clue_research.durable.enums import BudgetEventKind
from clue_research.durable.spans import (
    ATTR_BUDGET_SCOPE,
    ATTR_BUDGET_VERDICT,
    ATTR_CAP_CENTS,
    ATTR_PROJECTED_CENTS,
    SPAN_BUDGET_CHECK,
    SPAN_BUDGET_ESTIMATE,
)
from clue_research.obs import (
    ATTR_CAMPAIGN_RUN_ID,
    METRIC_COST_CAP_CENTS,
    METRIC_COST_CENTS,
    apply_attributes,
    get_metric_sink,
    traced_step,
)

# --- errors ----------------------------------------------------------------------------------


class BudgetError(Exception):
    """Base error for the budget/cost-governance engine (M7.5)."""


class BudgetStateNotFound(BudgetError):
    """A :meth:`BudgetEngine.check` / :meth:`BudgetEngine.burn_down` needed an ``account_run`` /
    ``campaign_run`` row that does not exist — a misrouted check, not a budget outcome (it is
    raised, never silently treated as "uncapped", so a missing row can never let spend slip past
    the gate)."""


# --- the pre-run projection (pure — unit-testable without a store) -----------------------------


def _deep_fraction(cutoff: float) -> float:
    """Fraction of discovered accounts projected to clear ``cutoff`` and go deep.

    The honest part of the estimate: without the real Pass-A score distribution (M6's), the engine
    assumes scores are **uniform on [0, 1]**, so the share at-or-above a cutoff ``c`` is ``1 - c``
    (clamped to [0, 1] for out-of-range cutoffs). This is the one modelling assumption — surfaced
    by :attr:`Estimate.confidence` (0.5) rather than hidden — and is swappable behind the engine
    without changing any caller (conventions §2)."""
    return min(1.0, max(0.0, 1.0 - cutoff))


def project_spend(
    policy: BudgetCaps,
    *,
    discovered_count: int,
    tier_cutoffs: dict[str, float] | None = None,
) -> Estimate:
    """Project a campaign's spend (Doc C §5) — the pure math behind :meth:`BudgetEngine.estimate`.

    Decomposes as *"~N discovered → ~M go deep → est \\$X"*: every discovered account pays the cheap
    deterministic Pass-A cost; the share that clears the tier cutoffs goes deep at its tier's
    per-account band. Tiers are **nested** (an account clearing the ``top`` cutoff also clears
    ``high``), so each account is counted once at its *highest* qualifying tier and priced at that
    tier's band — no double-count. Each deep account is priced at its tier's **cap** (the maximum it
    may spend), so the per-account cost is the conservative end of the band; the deep *count* is the
    **expected** share under the uniform-score model (:func:`_deep_fraction`) — a projection, not a
    hard ceiling, which is why the result carries ``confidence`` (0.5), not certainty.

    Counts round at **cumulative** tier boundaries (count-through-this-tier minus count-through-the
    stricter tiers), so the per-tier marginals always sum to ``round(n × total-deep-share)`` — they
    cannot drift above the rounded total the way independently-rounded marginals would.

    With no cutoffs only Pass A is projected (you cannot go deep without tiers). The result's
    ``confidence`` reflects the uniform-score assumption in :func:`_deep_fraction`."""
    n = max(0, discovered_count)
    pass_a = Decimal(n) * policy.pass_a_cap_cents_per_account

    # Sanitise client-supplied cutoffs: keep only real, finite numbers (drop bool/NaN/inf).
    clean = {
        tier: float(cutoff)
        for tier, cutoff in (tier_cutoffs or {}).items()
        if isinstance(cutoff, (int, float))
        and not isinstance(cutoff, bool)
        and math.isfinite(cutoff)
    }
    # Highest cutoff first so the cumulative deep-share grows monotonically down the tiers: each
    # tier's marginal count is (accounts through this tier) − (accounts through the stricter tiers),
    # attributing each account once to its top qualifying tier at that tier's band.
    ordered = sorted(clean.items(), key=lambda kv: kv[1], reverse=True)

    prev_count = 0
    projected_deep_count = 0
    pass_b = Decimal(0)
    for tier, cutoff in ordered:
        # Round the *cumulative* count, then take the marginal — so the per-tier counts sum exactly
        # to the rounded total share (independently rounding each marginal would not).
        count_through = round(n * _deep_fraction(cutoff))
        marginal = max(0, count_through - prev_count)
        per_account = policy.per_account_cap_for(tier)
        if per_account is not None:
            pass_b += Decimal(marginal) * per_account
        projected_deep_count = max(projected_deep_count, count_through)
        prev_count = max(prev_count, count_through)

    estimated = pass_a + pass_b
    cost_per_account = (
        pass_b / Decimal(projected_deep_count) if projected_deep_count else Decimal(0)
    )
    return Estimate(
        discovered_count=n,
        projected_deep_count=projected_deep_count,
        estimated_cost_cents=estimated,
        cost_per_account_cents=cost_per_account,
    )


# --- the persistence seam --------------------------------------------------------------------


@runtime_checkable
class BudgetStore(Protocol):
    """The persistence seam the budget engine reads/writes cost state through (M7.5).

    Abstracting persistence keeps the estimate/check/record/burn-down logic testable on an in-memory
    store without Postgres, and keeps the accounting backend swappable (conventions §2). The
    production implementation is :class:`DbBudgetStore`."""

    async def run_state(self, campaign_run_id: CampaignRunId) -> RunBudgetState | None: ...

    async def account_state(self, account_run_id: RunId) -> AccountBudgetState | None: ...

    async def add_spend(
        self,
        *,
        campaign_run_id: CampaignRunId,
        cost_cents: CostCents,
        account_run_id: RunId | None = None,
        conn: AsyncConnection | None = None,
    ) -> None: ...

    async def set_campaign_cap(
        self, campaign_run_id: CampaignRunId, cap_cents: CostCents
    ) -> None: ...

    async def set_account_cap(self, account_run_id: RunId, cap_cents: CostCents | None) -> None: ...

    async def set_estimated(
        self, campaign_run_id: CampaignRunId, estimated_cents: CostCents
    ) -> None: ...

    async def record_event(
        self,
        *,
        campaign_run_id: CampaignRunId,
        scope: BudgetScope,
        kind: BudgetEventKind,
        projected_cents: CostCents,
        cap_cents: CostCents | None,
        detail: dict[str, JsonValue] | None = None,
    ) -> None: ...


class DbBudgetStore:
    """The Postgres :class:`BudgetStore` — the production cost-accounting path (M7.5).

    Each method runs in its own ``db.transaction()`` (mirroring :class:`DbCampaignRunStore` /
    :class:`DbIdempotencyStore`). ``add_spend`` increments the run total and, when an
    ``account_run_id`` is given, the per-account total in the **same** transaction, so the two
    counters never drift across a crash between them."""

    async def run_state(self, campaign_run_id: CampaignRunId) -> RunBudgetState | None:
        async with transaction() as conn:
            return await get_run_budget_state(conn, campaign_run_id)

    async def account_state(self, account_run_id: RunId) -> AccountBudgetState | None:
        async with transaction() as conn:
            return await get_account_budget_state(conn, account_run_id)

    async def add_spend(
        self,
        *,
        campaign_run_id: CampaignRunId,
        cost_cents: CostCents,
        account_run_id: RunId | None = None,
        conn: AsyncConnection | None = None,
    ) -> None:
        # Raise on a 0-row increment (a charge against a missing run/account) so a charge can never
        # silently vanish — the write-path analogue of ``check``'s fail-loud-on-missing-row rule.
        # Run + account increment in ONE transaction: a missing account rolls the run back too.
        #
        # ``conn`` (M8A.4): when the caller supplies a connection, the increments run on **its**
        # transaction — so the charge commits atomically with the claim writes + the M7.4 ledger
        # ``succeed`` the caller also does on that conn (the airtight exactly-once the ``record``
        # docstring deferred to "the M8 claim-write path"). When omitted, the increments open their
        # own transaction exactly as before (today's M6/M7/M9 callers are unchanged).
        if conn is not None:
            await self._add_spend(conn, campaign_run_id, cost_cents, account_run_id)
            return
        async with transaction() as own_conn:
            await self._add_spend(own_conn, campaign_run_id, cost_cents, account_run_id)

    @staticmethod
    async def _add_spend(
        conn: AsyncConnection,
        campaign_run_id: CampaignRunId,
        cost_cents: CostCents,
        account_run_id: RunId | None,
    ) -> None:
        if await add_run_spend(conn, campaign_run_id, cost_cents) == 0:
            raise BudgetStateNotFound(f"campaign_run {campaign_run_id}")
        if (
            account_run_id is not None
            and await add_account_spend(conn, account_run_id, cost_cents) == 0
        ):
            raise BudgetStateNotFound(f"account_run {account_run_id}")

    async def set_campaign_cap(self, campaign_run_id: CampaignRunId, cap_cents: CostCents) -> None:
        async with transaction() as conn:
            await set_budget_cap(conn, campaign_run_id, cap_cents)

    async def set_account_cap(self, account_run_id: RunId, cap_cents: CostCents | None) -> None:
        async with transaction() as conn:
            await set_account_budget_cap(conn, account_run_id, cap_cents)

    async def set_estimated(
        self, campaign_run_id: CampaignRunId, estimated_cents: CostCents
    ) -> None:
        async with transaction() as conn:
            await set_estimated_cents(conn, campaign_run_id, estimated_cents)

    async def record_event(
        self,
        *,
        campaign_run_id: CampaignRunId,
        scope: BudgetScope,
        kind: BudgetEventKind,
        projected_cents: CostCents,
        cap_cents: CostCents | None,
        detail: dict[str, JsonValue] | None = None,
    ) -> None:
        async with transaction() as conn:
            await insert_budget_event(
                conn,
                campaign_run_id=campaign_run_id,
                scope=scope,
                kind=kind,
                projected_cents=projected_cents,
                cap_cents=cap_cents,
                detail=detail,
            )


# --- the engine ------------------------------------------------------------------------------


class BudgetEngine:
    """The cost-governance engine (M7.5) — the concrete :class:`clue_core.BudgetEngine`.

    Construct once with the run's resolved :class:`~clue_research.config.BudgetCaps` policy (the api
    root reads ``get_config(client, icp).budget_caps``) and a :class:`BudgetStore`. It is the
    single chokepoint for spend authorisation: Pass-A scoring (M6), deep workers (M8), and
    verification (M9) call :meth:`check` before spending and :meth:`record` after; the state
    machine (M7.3) calls
    :meth:`estimate` for the pre-run figure, gates expensive phases on :meth:`check`, and exposes
    :meth:`burn_down` for the live surface. No worker/phase can overspend around it."""

    def __init__(
        self,
        *,
        policy: BudgetCaps | None = None,
        store: BudgetStore | None = None,
    ) -> None:
        self._policy = policy if policy is not None else BudgetCaps()
        self._store: BudgetStore = store if store is not None else DbBudgetStore()

    @property
    def policy(self) -> BudgetCaps:
        """The versioned budget policy this engine enforces (config, not code)."""
        return self._policy

    async def estimate(
        self,
        campaign_run_id: CampaignRunId,
        *,
        discovered_count: int,
        tier_cutoffs: dict[str, float] | None = None,
    ) -> Estimate:
        """Project the run's spend before any deep spend (Doc C §5) and persist it on the run so the
        burn-down surface can show spent-vs-estimate. The projection itself is pure
        (:func:`project_spend`); persistence is best-effort (a no-op if the run row does not exist
        yet — a true pre-start estimate)."""
        estimate = project_spend(
            self._policy, discovered_count=discovered_count, tier_cutoffs=tier_cutoffs
        )
        with traced_step(
            SPAN_BUDGET_ESTIMATE,
            **{ATTR_CAMPAIGN_RUN_ID: str(campaign_run_id)},
        ) as span:
            await self._store.set_estimated(campaign_run_id, estimate.estimated_cost_cents)
            apply_attributes(
                span,
                {
                    ATTR_PROJECTED_CENTS: str(estimate.estimated_cost_cents),
                    "discovered_count": str(estimate.discovered_count),
                    "projected_deep_count": str(estimate.projected_deep_count),
                },
            )
        return estimate

    async def check(
        self,
        *,
        scope: BudgetScope,
        projected_cents: CostCents,
        campaign_run_id: CampaignRunId,
        entity_id: EntityId | None = None,
        account_run_id: RunId | None = None,
    ) -> BudgetDecision:
        """Authorise a prospective spend of ``projected_cents`` at ``scope`` *before* it happens.

        * ``ACCOUNT`` — needs ``account_run_id``. Cap = the account's row override, else the
          per-tier policy band. A breach is ``DENY`` (the M7.2 within-cap-depth spawn-denial; strict
          ``>`` — a spend that exactly fits is allowed).
        * ``PASS`` — the cheap Pass-A per-account ceiling. A breach is ``DENY`` (strict ``>``).
        * ``RUN`` — the per-campaign hard cap. A breach is ``GRACEFUL_STOP`` (inclusive ``>=`` —
          keep spend strictly under the hard cap; this is also what lets a ``projected=0`` pre-gate
          fire exactly when a cap was lowered below current spend).

        An uncapped scope always ``ALLOW``\\s (the per-campaign cap stays the backstop). A non-allow
        verdict appends the matching ``budget_event``; the decision is traced regardless."""
        if scope is BudgetScope.ACCOUNT:
            if account_run_id is None:
                raise ValueError("ACCOUNT-scope check requires account_run_id")
            state = await self._store.account_state(account_run_id)
            if state is None:
                raise BudgetStateNotFound(f"account_run {account_run_id}")
            cap = (
                state.budget_cap_cents
                if state.budget_cap_cents is not None
                else self._policy.per_account_cap_for(state.tier)
            )
            verdict = self._verdict(
                spent=state.cost_cents,
                projected=projected_cents,
                cap=cap,
                breach_verdict=BudgetVerdict.DENY,
                inclusive=False,
            )
        elif scope is BudgetScope.PASS:
            cap = self._policy.pass_a_cap_cents_per_account
            verdict = self._verdict(
                spent=Decimal(0),
                projected=projected_cents,
                cap=cap,
                breach_verdict=BudgetVerdict.DENY,
                inclusive=False,
            )
        else:  # RUN
            run = await self._store.run_state(campaign_run_id)
            if run is None:
                raise BudgetStateNotFound(f"campaign_run {campaign_run_id}")
            cap = run.cap_cents
            verdict = self._verdict(
                spent=run.spent_cents,
                projected=projected_cents,
                cap=cap,
                breach_verdict=BudgetVerdict.GRACEFUL_STOP,
                inclusive=True,
            )

        decision = BudgetDecision(
            verdict=verdict,
            scope=scope,
            projected_cents=projected_cents,
            cap_cents=cap if cap is not None else Decimal(0),
        )
        with traced_step(SPAN_BUDGET_CHECK, **{ATTR_CAMPAIGN_RUN_ID: str(campaign_run_id)}) as span:
            apply_attributes(
                span,
                {
                    ATTR_BUDGET_SCOPE: scope.value,
                    ATTR_BUDGET_VERDICT: verdict.value,
                    ATTR_PROJECTED_CENTS: str(projected_cents),
                    ATTR_CAP_CENTS: str(decision.cap_cents),
                },
            )
        if verdict is not BudgetVerdict.ALLOW:
            kind = (
                BudgetEventKind.GRACEFUL_STOP
                if verdict is BudgetVerdict.GRACEFUL_STOP
                else BudgetEventKind.CHECK_DENY
            )
            detail: dict[str, JsonValue] = {}
            if entity_id is not None:
                detail["entity_id"] = str(entity_id)
            if account_run_id is not None:
                detail["account_run_id"] = str(account_run_id)
            await self._store.record_event(
                campaign_run_id=campaign_run_id,
                scope=scope,
                kind=kind,
                projected_cents=projected_cents,
                cap_cents=cap,
                detail=detail or None,
            )
        return decision

    async def record(
        self,
        *,
        cost_cents: CostCents,
        scope: BudgetScope,
        campaign_run_id: CampaignRunId,
        entity_id: EntityId | None = None,
        account_run_id: RunId | None = None,
        conn: AsyncConnection | None = None,
    ) -> None:
        """Record an actual charge — the **single** live increment of the spend counters
        (``campaign_run.spent_cents``, plus ``account_run.cost_cents`` when ``account_run_id`` is
        given). Call exactly once per ledger charge, inside the M7.4 ``idempotent`` EXECUTE branch
        (never on a replay), so the counters track the ledger's ``cost_cents_charged``.

        Routing is driven purely by ``account_run_id`` (present → the account counter moves too);
        ``scope`` / ``entity_id`` are carried for protocol symmetry with :meth:`check` + telemetry,
        not for routing. A charge against a non-existent run/account raises
        :class:`BudgetStateNotFound` (fail-loud, symmetric with :meth:`check`) — a charge never
        silently vanishes.

        **Exactly-once (M8A.4).** Pass ``conn`` to commit the increment on the **caller's**
        transaction, atomically with the claim write(s) and the M7.4 ledger ``succeed`` the caller
        does on the same connection — closing the crash window the V1 caveat below named (the deep
        committee/contact spend path is the caller that closes it; see
        ``clue_research.api.deep.spend``). This is an extension of the frozen ``core.BudgetEngine``
        protocol that lives only on the concrete engine.

        **Transactional caveat (V1, when ``conn`` is omitted):** the increment commits in its own
        transaction, separate from the ledger ``succeed``. Airtight exactly-once then requires the
        caller to commit the charge *and* finish the ledger in **one** transaction — which the
        ``conn`` parameter now enables. Without it the increment is the single live counter and
        reconciles with the ledger because it runs once on the EXECUTE branch."""
        if cost_cents < 0:
            raise ValueError(f"cost_cents must be >= 0 (got {cost_cents})")
        await self._store.add_spend(
            campaign_run_id=campaign_run_id,
            cost_cents=cost_cents,
            account_run_id=account_run_id,
            conn=conn,
        )

    async def set_campaign_cap(self, campaign_run_id: CampaignRunId, cap_cents: CostCents) -> None:
        """Set the per-campaign hard cap (the client raise/lower loop). Always records a
        ``cap_raised`` governance event (the single cap-change kind); when current spend has reached
        the new cap (``spent >= cap``) it additionally records ``breach_pending`` — the run is now
        out of budget and must be raised again or have its cutoffs tightened before the next spend
        phase proceeds. The ``>=`` boundary matches the RUN-scope graceful-stop gate exactly (which
        stops at ``spent + 0 >= cap``), so ``breach_pending`` is recorded for *precisely* the caps
        the pre-gate will then graceful-stop on — the two boundaries are provably consistent."""
        if cap_cents < 0:
            raise ValueError(f"cap_cents must be >= 0 (got {cap_cents})")
        await self._store.set_campaign_cap(campaign_run_id, cap_cents)
        run = await self._store.run_state(campaign_run_id)
        spent = run.spent_cents if run is not None else Decimal(0)
        await self._store.record_event(
            campaign_run_id=campaign_run_id,
            scope=BudgetScope.RUN,
            kind=BudgetEventKind.CAP_RAISED,
            projected_cents=spent,
            cap_cents=cap_cents,
        )
        if run is not None and spent >= cap_cents:
            await self._store.record_event(
                campaign_run_id=campaign_run_id,
                scope=BudgetScope.RUN,
                kind=BudgetEventKind.BREACH_PENDING,
                projected_cents=spent,
                cap_cents=cap_cents,
            )

    async def burn_down(self, campaign_run_id: CampaignRunId) -> BurnDown:
        """The live cost accounting (Doc C §5/§6) — spent vs estimate vs cap vs remaining for the
        run. ``remaining_cents`` is ``max(0, cap − spent)`` (clamped: ``CostCents`` is non-negative,
        so an over-budget run reads 0 remaining, not a negative); both ``cap_cents`` and
        ``estimated_cents`` read 0 when never set. Emits the Doc C §6 cost gauges for the M13.4
        surface. Per-pass / per-source breakdowns are left to M13 (derived from claim provenance via
        :func:`clue_research.obs.record_source_yield`), so they default empty here."""
        run = await self._store.run_state(campaign_run_id)
        if run is None:
            raise BudgetStateNotFound(f"campaign_run {campaign_run_id}")
        spent = run.spent_cents
        cap = run.cap_cents if run.cap_cents is not None else Decimal(0)
        estimated = run.estimated_cents if run.estimated_cents is not None else Decimal(0)
        remaining = (
            max(Decimal(0), run.cap_cents - spent) if run.cap_cents is not None else Decimal(0)
        )
        sink = get_metric_sink()
        sink.gauge(METRIC_COST_CENTS, float(spent), {ATTR_CAMPAIGN_RUN_ID: str(campaign_run_id)})
        if run.cap_cents is not None:
            sink.gauge(
                METRIC_COST_CAP_CENTS,
                float(run.cap_cents),
                {ATTR_CAMPAIGN_RUN_ID: str(campaign_run_id)},
            )
        return BurnDown(
            spent_cents=spent,
            estimated_cents=estimated,
            cap_cents=cap,
            remaining_cents=remaining,
        )

    def _verdict(
        self,
        *,
        spent: CostCents,
        projected: CostCents,
        cap: CostCents | None,
        breach_verdict: BudgetVerdict,
        inclusive: bool,
    ) -> BudgetVerdict:
        """ALLOW when uncapped or within cap; ``breach_verdict`` (DENY / GRACEFUL_STOP) on breach.
        ``inclusive`` selects ``>=`` (RUN — keep spend strictly under the hard cap) vs ``>``
        (ACCOUNT / PASS — an exact-fit spend is allowed)."""
        if cap is None:
            return BudgetVerdict.ALLOW
        total = spent + projected
        breached = total >= cap if inclusive else total > cap
        return breach_verdict if breached else BudgetVerdict.ALLOW
