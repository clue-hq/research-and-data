"""Typed proposal / edit / diff / confirmation shapes for ICP synthesis (M5.2).

The platform **suggests, the client confirms** (Doc B §1): synthesis emits structured
:class:`ICPProposal` hypotheses (never prose), the client edits them (:class:`ICPProposalEdits`),
and confirmation compiles the edited proposal into a versioned ``ICPSpec`` while recording the
suggested-vs-confirmed :class:`ICPProposalDiff` as labeled feedback (substrate §9/§10).

These are *transient until confirmed* — the proposal is the contract with the (out-of-repo)
client-facing editor; downstream (M6 discovery, M6 Pass A, M4 source planning) consumes only the
compiled ``ICPSpec`` (:class:`ICPSpecRef`), never the proposal internals, so the synthesis model is
fully swappable behind the compiled-spec seam (conventions §2). Every proposed element carries
``justifying_claim_ids`` — the Client-KB claim ids that justify it (no element justified by
"synthesis thought it was a good idea").
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue

from clue_core import ClaimId, EntityId, Estimate, UnitInterval

# --- the six proposal elements (Doc B §3) ----------------------------------


class FirmographicDimensions(BaseModel):
    """Element 1 — firmographic constraints (industry/vertical, size band, geo, revenue band) plus
    the registered ``field_key``s that back them (e.g. ``core.employee_count`` for a size band). The
    constraint *values* drive M6 discovery (carried in the spec's ``discovery_strategy``); the
    ``field_keys`` enter the active research set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    industry: str | None = None
    size_band: str | None = None
    geo: str | None = None
    revenue_band: str | None = None
    field_keys: tuple[str, ...] = ()
    justifying_claim_ids: tuple[ClaimId, ...] = ()


class TechnographicDimension(BaseModel):
    """Element 2 — one pack-specific (``<pack>.*``) vertical dimension that matters for this
    industry (substrate §3 packs). ``pack_key`` is the catalog key whose ``enabled_packs`` entry
    carries it into the compiled plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: str
    pack_key: str
    value_constraint: str | None = None
    justifying_claim_ids: tuple[ClaimId, ...] = ()


class CandidateSignal(BaseModel):
    """Element 3 — a proposed *signal class* under Doc C's two-tier signal model (Doc C §1).

    Every signal class splits into a **cheap proxy** and an optional **deep narrative**. The proxy
    is a deterministic, tier-1/2 registry field tagged ``pass_kind=scoring`` — resolved on *all*
    accounts in Pass A to produce fit/intent scores cheaply. The narrative is a ``pass_kind=deep``
    field — often tier-4 synthesis — resolved only on high-tier accounts in Pass B once an account
    has earned deeper spend. M1 discovery stays existence-only; signal richness lives here, in Pass
    A/B, not in discovery.

    This type is the *proposal-layer* grouping: synthesis suggests which proxy and narrative fields
    belong to one theme; the client may drop whole classes via
    :attr:`ICPProposalEdits.removed_signal_classes`. At confirm, both key tuples merge into the
    compiled spec's active field set and ``signal_class`` names feed
    ``discovery_strategy.candidate_signal_classes``; the durable proxy↔narrative link in
    :class:`~clue_research.icp.compiler.SignalClassLink` is rebuilt from each field's registry
    ``signal_class`` + ``pass_kind``.

    Attributes:
        signal_class: Human-readable theme name (``"growth"``, ``"intent"``, ``"saas_vertical"``).
            Groups the proxy and narrative fields; also the handle the client edits/removes.
        proxy_field_keys: Pass-A scoring fields — cheap deterministic facts for the whole list
            (e.g. ``account.recent_funding``, headcount trend). Weighted in the proposed rubric's
            ``intent`` (or ``fit``) dimension; must be ``pass_kind=scoring`` registry keys.
        narrative_field_keys: Pass-B deep fields — synthesized "why" for high-tier accounts only
            (e.g. ``account.hiring_velocity_eng``, strategic-moves narrative). May be empty when
            the signal is proxy-only (firmographics rarely need synthesis).
        justifying_claim_ids: Client-KB claim ids that justify proposing this signal — no element
            may rest on "synthesis thought it was a good idea" alone.

    Example (floor synthesis — growth signal)::

        CandidateSignal(
            signal_class="growth",
            proxy_field_keys=("account.recent_funding",),       # Pass A: Crunchbase/API fact
            narrative_field_keys=("account.hiring_velocity_eng",),  # Pass B: deep hiring read
            justifying_claim_ids=(...),  # from client.delivered_value / client.icp_evidence
        )

    At runtime: Pass A scores every account on ``account.recent_funding``; only accounts that tier
    high enough trigger Pass B to synthesize ``account.hiring_velocity_eng`` — same ``growth``
    theme, two execution depths."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_class: str
    proxy_field_keys: tuple[str, ...] = ()
    narrative_field_keys: tuple[str, ...] = ()
    justifying_claim_ids: tuple[ClaimId, ...] = ()


class SeedAccount(BaseModel):
    """Element 4 — a resolved seed ``account_entity`` (never free-text — conventions §2): a client
    customer / case-study anchor (from M5.1) or a high-fit import (from M5.3), assembled and ranked
    by M5.4. M5.2 carries seeds the client/M5.4 supply; it never resolves names nor discovers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_entity_id: EntityId
    seed_reason: str  # existing_customer | case_study | high_fit_import | crm_customer
    seed_confidence: UnitInterval = 0.5
    justifying_claim_ids: tuple[ClaimId, ...] = ()


class SourcePrior(BaseModel):
    """One row in the ICP proposal's source-profile *preview* (staged-flow §7c).

    Different ICPs/industries need different sources prioritized (e.g. arXiv **high** for
    frontier AI, BuiltWith **high** for data infra). At runtime the Source Planner reads weighted
    priors to pick and order sources per field; this type surfaces that choice to the client
    *before* confirm. Synthesis copies these from each enabled pack's catalog defaults
    (:class:`~clue_research.icp.source_profile.WeightedSource`); it is proposal-layer only — the
    authoritative profile is served at runtime from ``enabled_packs`` (M4.6).

    Attributes:
        source_key: Registered source id (``"arxiv"``, ``"builtwith"``, ``"g2"``, …).
        weight: Ordinal trust band (``SourceWeight``: ``high`` / ``medium`` / ``low``).
        rank: 1-based consult order when several sources could apply."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str
    weight: str  # SourceWeight value
    rank: int


class StartingSourceProfile(BaseModel):
    """Element 5 — *which sources matter for this ICP* (Doc B §3 / staged-flow §7).

    Fields say *what* to research; source profiles say *where* to learn it and how much to trust
    each place — per industry pack. Synthesis proposes enabled ``packs`` plus a flattened ``priors``
    preview so the client can inspect source trust/order before spend, not discover it only after
    discovery/deep research starts. Only ``packs`` compiles into the spec
    (``enabled_packs`` → ``source_profile_ref``); at confirm the full weighted profile is reloaded
    from the pack catalog via :func:`~clue_research.icp.serve_source_profile`. ``priors`` is
    denormalized transparency — same information the planner will use, shown alongside the pack
    choice in the (out-of-repo) editor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    packs: tuple[str, ...] = ()
    priors: tuple[SourcePrior, ...] = ()
    justifying_claim_ids: tuple[ClaimId, ...] = ()


class RubricWeight(BaseModel):
    """One proposed scoring-rubric contribution: a ``field_key`` weighted into the ``fit`` or
    ``intent`` dimension via a declarative ``transform`` (Doc C §1 / M3.4). Both dimensions read
    Pass-A scoring proxies only (``validate_rubric`` enforces this at confirm)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: str
    dimension: str  # ScoreDimension value: "fit" | "intent"
    weight: float = 1.0
    transform: str = "boolean"  # ScoringTransform value
    params: dict[str, JsonValue] = {}
    justifying_claim_ids: tuple[ClaimId, ...] = ()


class ProposedRubric(BaseModel):
    """Element 6 — the proposed fit + intent scoring rubric (weights + tiering thresholds). Compiles
    into a :class:`~clue_research.icp.ScoringRubric` slot of the ICP spec at confirm."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    weights: tuple[RubricWeight, ...] = ()
    fit_threshold: UnitInterval = 0.0
    intent_threshold: UnitInterval = 0.0


class ICPProposal(BaseModel):
    """A candidate ICP — a structured hypothesis with all six Doc B §3 elements. One client may get
    several (D5 multi-ICP) when customer evidence clusters into distinct segments; ``icp_key``
    distinguishes them under the client. Transient until :func:`~clue_research.stage0.icp_confirm`
    confirms it into a versioned ``ICPSpec``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    icp_key: str
    label: str | None = None
    rationale: str | None = None  # why this segment (and why a split, for a secondary ICP)
    firmographic: FirmographicDimensions = FirmographicDimensions()
    technographic: tuple[TechnographicDimension, ...] = ()
    candidate_signals: tuple[CandidateSignal, ...] = ()
    seed_accounts: tuple[SeedAccount, ...] = ()
    source_profile: StartingSourceProfile = StartingSourceProfile()
    rubric: ProposedRubric = ProposedRubric()
    justifying_claim_ids: tuple[ClaimId, ...] = ()  # the Client-KB claims the synthesis read


# --- edits + diff ----------------------------------------------------------


class ICPProposalEdits(BaseModel):
    """The client's edits to a proposal before confirmation (always-has-the-wheel — Doc B §1). All
    fields default empty (confirm-as-proposed). ``icp_key`` renames the segment; a weight override
    sets a field's rubric weight (``0.0`` drops it). The compiled spec reflects exactly these edits,
    and the suggested-vs-confirmed :class:`ICPProposalDiff` records them as labeled feedback."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    icp_key: str | None = None
    removed_signal_classes: tuple[str, ...] = ()
    removed_field_keys: tuple[str, ...] = ()
    added_field_keys: tuple[str, ...] = ()
    removed_packs: tuple[str, ...] = ()
    added_packs: tuple[str, ...] = ()
    removed_seed_ids: tuple[EntityId, ...] = ()
    rubric_weight_overrides: dict[str, float] = {}  # field_key -> new weight (0.0 removes it)
    fit_threshold: UnitInterval | None = None
    intent_threshold: UnitInterval | None = None
    notes: str | None = None  # the client's explanation, kept with the diff


class RubricWeightChange(BaseModel):
    """A single rubric-weight change in the confirm diff (``None`` before = added; ``None`` after =
    removed)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: str
    before: float | None = None
    after: float | None = None


class ICPProposalDiff(BaseModel):
    """The structural suggested-vs-confirmed difference, persisted claim-native as labeled feedback
    (substrate §9/§10). Empty when the client confirmed as proposed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    added_field_keys: tuple[str, ...] = ()
    removed_field_keys: tuple[str, ...] = ()
    added_packs: tuple[str, ...] = ()
    removed_packs: tuple[str, ...] = ()
    removed_signal_classes: tuple[str, ...] = ()
    removed_seed_ids: tuple[EntityId, ...] = ()
    reweighted: tuple[RubricWeightChange, ...] = ()
    fit_threshold_before: float | None = None
    fit_threshold_after: float | None = None
    intent_threshold_before: float | None = None
    intent_threshold_after: float | None = None
    notes: str | None = None

    @property
    def is_empty(self) -> bool:
        """True when the client confirmed the proposal unedited (a no-op diff)."""
        return not (
            self.added_field_keys
            or self.removed_field_keys
            or self.added_packs
            or self.removed_packs
            or self.removed_signal_classes
            or self.removed_seed_ids
            or self.reweighted
            or self.fit_threshold_after is not None
            or self.intent_threshold_after is not None
        )


# --- confirmation outputs --------------------------------------------------


class ICPSpecRef(BaseModel):
    """A handle to a confirmed, versioned ``ICPSpec`` — the single contract downstream executes
    against. Note the spec is keyed ``(client_id, icp_key, version)`` (M3.1): there is **no**
    ``icp_id``; the spec's nominal ``icp_id`` is the ``(client_id, icp_key)`` pair, with ``version``
    pinning the immutable spec a campaign reproduces from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_id: str
    icp_key: str
    icp_version: int


class ICPConfirmation(BaseModel):
    """What :func:`~clue_research.stage0.icp_confirm.confirm_icp` returns: the confirmed spec
    reference, the suggested-vs-confirmed diff (also persisted), and the pre-run cost
    :class:`~clue_core.execution.Estimate` surfaced before any discovery/scoring spend
    (Doc C §5). The estimate reuses the frozen M7 ``BudgetEngine.estimate`` value type — pre-
    discovery its ``discovered_count`` is a projected addressable prior (low ``confidence``), and
    once M7's real ``BudgetEngine`` is injected it returns the authoritative figure unchanged."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ICPSpecRef
    diff: ICPProposalDiff
    estimate: Estimate
