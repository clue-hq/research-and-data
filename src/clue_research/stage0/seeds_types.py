"""Typed shapes for hybrid lookalike seeding (M5.4).

Import and discovery are **not exclusive** (Doc B §4 Hybrid): a client's imported list, plus the
existing customers surfaced during reverse-profiling, are the **strongest seeds for lookalike
discovery** — "accounts like yours you may have missed". This module carries the contracts for the
seed assembler (:func:`~clue_research.stage0.seeds.assemble_lookalike_seeds`):

* :class:`SeedReason` — *why* an entity is a seed, so the lookalike candidates M6 derives inherit an
  explainable provenance ("found as a lookalike of your customer Acme").
* :class:`SeedPolicy` — the seed-ranking heuristic (identity confidence × fit × customer-status) as
  **versioned config**, swappable per client/ICP without code (conventions §2). The actual lookalike
  *expansion* algorithm is M6's and invisible here.
* :class:`SkippedSeed` — customer evidence that could not become a clean seed, surfaced **with a
  reason** (never silently dropped — same discipline as the import path's ``unresolved``).
* :class:`SeedSet` — the assembled, ranked, **per-ICP** seed set: the input contract to M6 mode-M1
  lookalike expansion (staged-flow §3). Its ``seeds`` are the frozen
  :class:`~clue_research.stage0.icp_types.SeedAccount` primitives, so a SeedSet slots straight into
  an :class:`~clue_research.stage0.icp_types.ICPProposal`'s ``seed_accounts`` and reaches M6 through
  the confirmed spec's ``discovery_strategy.seed_account_ids`` — store/spec-mediated, no import.

Every seed is a **resolved ``account_entity_id``, never a free-text name** (the M2 invariant,
conventions §2): the assembler resolves customer evidence through the identity service before any
entity becomes a seed.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from clue_research.core import UnitInterval
from clue_research.stage0.icp_types import SeedAccount

# --- why an entity is a seed -----------------------------------------------


class SeedReason(StrEnum):
    """The provenance of a lookalike seed — its value carried on each
    :class:`~clue_research.stage0.icp_types.SeedAccount` so downstream lookalike candidates can cite
    the anchor ("lookalike of your customer Acme"). Ordered by anchor strength in
    :func:`reason_rank` (a CRM-confirmed customer is a stronger anchor than a high-fit import)."""

    CRM_CUSTOMER = "crm_customer"  # M5.3 import flagged already_customer (CRM tier-1 relationship)
    EXISTING_CUSTOMER = "existing_customer"  # M5.1 client.customer evidence (a customers page)
    CASE_STUDY = "case_study"  # (reserved) an entity behind a case study / testimonial / logo
    HIGH_FIT_IMPORT = (
        "high_fit_import"  # M5.3 resolved import above the ICP fit floor (not a customer)
    )


def reason_rank(reason: SeedReason) -> int:
    """Anchor-strength rank (higher wins on dedup): a CRM-confirmed customer beats a page-claimed
    customer beats a high-fit import. Used when one entity is surfaced by more than one source."""
    return {
        SeedReason.CRM_CUSTOMER: 3,
        SeedReason.EXISTING_CUSTOMER: 2,
        SeedReason.CASE_STUDY: 2,
        SeedReason.HIGH_FIT_IMPORT: 1,
    }[reason]


def is_customer_reason(reason: SeedReason) -> bool:
    """A genuine-customer anchor (gets the customer-status confidence bonus in ranking)."""
    return reason in (SeedReason.CRM_CUSTOMER, SeedReason.EXISTING_CUSTOMER, SeedReason.CASE_STUDY)


# --- policy-as-data: the seed-ranking heuristic ----------------------------


class SeedPolicy(BaseModel):
    """The seed selection + ranking policy (conventions §2 — *policy is data*). The assembler reads
    these knobs; nothing here is hardcoded in the orchestration, so a client/ICP can tune which
    anchors qualify without a code change.

    ``seed_confidence`` blends identity confidence, ICP fit, and customer status:
    ``clamp(w_resolution·resolution_confidence + w_fit·fit + (customer_bonus if customer else 0))``.
    A candidate is kept iff it clears **all** of: ``min_resolution_confidence`` (clean identity),
    ``min_seed_confidence`` (the soft floor), and the ICP's own fit floor (per-ICP partition)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Clean anchors only: a deterministic/high-confidence identity match. A deterministic domain hit
    # scores 1.0; a fuzzy name match caps well below this, so the default keeps fuzzy customers out.
    min_resolution_confidence: UnitInterval = 0.85
    # The soft confidence floor a candidate must clear to be a seed (below ⇒ down-ranked out).
    min_seed_confidence: UnitInterval = 0.5
    # Hard cap on the seed set (lookalike expansion starts from clean anchors, not a long tail).
    max_seeds: int = 50
    # Whether a customers-page entry with a usable domain but no matching store entity is admitted
    # as a fresh candidate (vs surfaced in ``skipped``). Default off: a freshly-admitted entity has
    # no claims, back-scores 0, and is excluded by any fit floor — so minting it is usually noise.
    admit_unmatched_customers: bool = False
    # seed_confidence blend weights (need not sum to 1; the result is clamped to [0,1]).
    w_resolution: float = 0.3
    w_fit: float = 0.5
    customer_bonus: float = 0.2

    def seed_confidence(
        self, *, resolution_confidence: float, fit: float, is_customer: bool
    ) -> float:
        """The blended seed confidence used for ranking + the soft floor, clamped to ``[0,1]``."""
        raw = (
            self.w_resolution * resolution_confidence
            + self.w_fit * fit
            + (self.customer_bonus if is_customer else 0.0)
        )
        return 0.0 if raw < 0.0 else 1.0 if raw > 1.0 else raw


DEFAULT_SEED_POLICY = SeedPolicy()


# --- outputs ---------------------------------------------------------------


class SkippedSeed(BaseModel):
    """A customer-evidence entry that could not be **resolved** to a clean anchor — surfaced **with
    a reason**, never silently dropped (the import path's ``unresolved`` discipline). The causes are
    identity-side: no usable identity, a match below the identity-confidence floor, or an unmatched
    entry the policy does not admit. (A candidate that resolves cleanly but back-scores below the
    fit floor is *not* skipped — it is simply not selected for **this** ICP; it stays in the Client
    KB and may anchor a different ICP, the per-ICP partition.)"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity_repr: str
    reason: str


class SeedSet(BaseModel):
    """The assembled, ranked, **per-ICP** lookalike seed set — the input contract to M6 mode-M1
    lookalike expansion (staged-flow §3). M5.4 produces seeds; M6 runs the grounded expand loop +
    existence gate, so the discovery engine (Exa Websets / Parallel FindAll / Clay lookalike) stays
    swappable behind M6 (conventions §2).

    ``seeds`` are resolved-entity :class:`~clue_research.stage0.icp_types.SeedAccount`s (never
    free-text), reusable directly as an :class:`~clue_research.stage0.icp_types.ICPProposal`'s
    ``seed_accounts``. ``suppressed`` is ``True`` when the client opted out of the hybrid default
    (always-has-the-wheel — Doc B §1): an empty, suppressed set leaves the import-only path intact.
    ``channels`` annotates which lookalike-expansion channels the seeds will anchor, feeding M6 /
    Doc C §7 coverage-confidence reporting (M5.4 supplies the inputs, not the estimate)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_id: str
    icp_key: str
    icp_version: int
    seeds: tuple[SeedAccount, ...] = ()
    suppressed: bool = False
    skipped: tuple[SkippedSeed, ...] = ()
    channels: tuple[str, ...] = ()

    @property
    def seed_count(self) -> int:
        return len(self.seeds)

    @property
    def customer_seed_count(self) -> int:
        """Seeds that are genuine customers (the strongest lookalike anchors) — the canonical
        :func:`is_customer_reason` predicate, so the count, the confidence bonus, and the channel
        label never disagree about what a customer anchor is (incl. ``case_study``)."""
        return sum(1 for s in self.seeds if is_customer_reason(SeedReason(s.seed_reason)))
