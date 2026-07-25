"""Typed input / output shapes for the import entry scenario (M5.3).

Accounts enter the subsystem two ways, **first-class and symmetric** (Doc B §4): discovery (M6) and
import (here). Import is not a trivial branch — a client list arrives as names/domains of varying
quality and each row must resolve to a canonical ``account_entity`` (via M2), or import quietly
fails with duplicates, wrong-entity collapses, and silently-dropped rows. The client picked these
accounts, but we still **back-score them against their own confirmed ICP** (M5.2) — "3 of your 200
accounts don't match the ICP you defined" is the highest-value early signal. Import skips
*discovery*, never *scoring*.

These are stage0-local contracts (extends-not-redefines — Beat-0 names no frozen ``ImportResult``):
inputs (:class:`ImportRow` / :class:`ImportContactRow`) and the output (:class:`ImportResult`) whose
``resolved`` set is the **same ``account_entity``-keyed shape the discovery path produces** — so the
Pass A scoring bridge and everything downstream cannot tell discovered from imported accounts except
by their provenance flavor (``matched_channel='import'``). The fit/intent back-scores are the frozen
:class:`~clue_core.Score` primitives (decomposed, each sub-score linking the claims behind
it), the same primitives that later compose ``account_handoff`` — not the full handoff object (M12).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, JsonValue

from clue_core import ClaimId, EntityId, Score, UseClass

# --- input: the messy free-text list ---------------------------------------


class ImportContactRow(BaseModel):
    """An optional contact attached to an import row (Doc B §4; Doc D §2/§4). Resolves *under* its
    account. Written with an ``identity_binding`` (``strong`` when a verified email/LinkedIn is
    present, else ``weak``) and a ``use_class`` tag at write time so M10's use-gate can govern it
    downstream — import does not bypass compliance tagging. ``use_class`` defaults to
    ``professional-public`` (the B2B backbone); the importer may mark a row ``sensitive`` to keep it
    out of outreach by default."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = None
    email: str | None = None
    linkedin_url: str | None = None
    title: str | None = None
    use_class: UseClass = UseClass.PROFESSIONAL_PUBLIC


class ImportRow(BaseModel):
    """One row of a client-imported list (CSV / paste / CRM pull): a free-text account identity of
    varying quality plus optional metadata and contacts. ``row_index`` is the caller's stable
    1-based position, echoed in every resolution outcome so the client can audit which row produced
    which entity. A row carrying no usable identity (no ``name``, ``domain``, or ``registry_ids``)
    cannot be resolved and surfaces in :attr:`ImportResult.unresolved` — never silently dropped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    row_index: int
    name: str | None = None
    domain: str | None = None
    registry_ids: dict[str, str] = {}
    geo: dict[str, JsonValue] | None = None
    aliases: tuple[str, ...] = ()
    contacts: tuple[ImportContactRow, ...] = ()


# --- output: the resolved / needs-review / unresolved partition ------------


class FitFlag(StrEnum):
    """The D6 non-fit decision for a back-scored imported account. ``NON_FIT`` is a *flag*, never an
    exclusion — the account stays in the researched list and the client decides keep/drop (the
    client may know something the ICP doesn't encode)."""

    FIT = "fit"
    NON_FIT = "non_fit"


class ResolvedAccount(BaseModel):
    """A resolved imported account — the **same ``account_entity``-keyed shape discovery emits**
    plus its back-score. ``fit_score`` / ``intent_score`` are the decomposed
    :class:`~clue_core.Score` primitives (each component linking the claims behind it — no
    score without evidence), computed against the confirmed ICP via the M5.2/M3.4 Pass-A scorer.
    ``provenance_claim_id`` points at the discovery-provenance claim (``matched_channel='import'``)
    that records where/why the entity entered, so the resolution is auditable. The durable
    ``account.scoring.*`` write is M6.3's at the SCORING phase — this back-score is the early
    import-time preview."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_entity_id: EntityId
    row_index: int
    fit_score: Score
    intent_score: Score
    fit_flag: FitFlag
    already_customer: bool = False
    crm_relationship: str | None = None  # CrmRelationship value, when CRM-enriched
    resolution_method: str  # "deterministic" | "intra_batch" | "new_entity"
    matched_signal: str  # the match key: domain | registry | name+geo | new_entity
    resolution_confidence: float
    provenance_claim_id: ClaimId | None = None


class NeedsReviewRow(BaseModel):
    """A mid-band row routed to the M2 human review queue rather than guessed (the wrong-entity-
    collapse guard: two genuinely-different same-name companies must never silently merge). Carries
    the enqueued ``task_id`` and the candidate entity ids a human will adjudicate. No entity is
    created or mutated for a needs-review row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    row_index: int
    task_id: EntityId
    top_score: float
    candidate_entity_ids: tuple[EntityId, ...] = ()
    reason: str = "mid-band match — routed to human review"


class UnresolvedRow(BaseModel):
    """A row that could not be turned into an entity at all — surfaced **with a reason**, never
    silently dropped (Doc B §4.1). Either the row carried no usable identity, or resolution errored
    (a poison row that ``resolve_many`` isolated). It mints no entity (no junk ``(unnamed)``
    candidates)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    row_index: int
    reason: str
    identity_repr: str = ""  # a human-readable echo of the row's identity fields


class ImportContactResult(BaseModel):
    """The outcome of resolving one imported contact under its account — the resolved/admitted
    ``contact_entity_id`` plus the governance tags stamped at write time (Doc D §2/§4). The
    ``lawful_basis`` is recorded on the contact claim's value (forward-compatible with M10.5's
    planned ``claim`` provenance column) so M10's use-gate can govern it without M5.3 importing
    ``compliance``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    account_entity_id: EntityId
    row_index: int
    identity_binding: str  # IdentityBinding value
    use_class: str  # UseClass value
    lawful_basis: str


class ImportResult(BaseModel):
    """What :func:`~clue_research.stage0.import_accounts.import_accounts` returns. ``resolved`` is
    the convergence set — shape-identical to the discovery path's account set, flowing into the same
    Pass A → tiering → checkpoint → Pass B path. ``needs_review`` and ``unresolved`` make the two
    non-resolving outcomes explicit (never silently dropped). The ``import_batch_id`` groups the run
    (persisted claim-native as the ``import.batch`` marker — extends, does not redefine)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    import_batch_id: str
    resolved: tuple[ResolvedAccount, ...] = ()
    needs_review: tuple[NeedsReviewRow, ...] = ()
    unresolved: tuple[UnresolvedRow, ...] = ()
    contacts: tuple[ImportContactResult, ...] = ()

    @property
    def row_count(self) -> int:
        """Total rows accounted for across the three outcomes (every input row lands in exactly
        one — the no-silent-drop invariant, checkable by the caller)."""
        return len(self.resolved) + len(self.needs_review) + len(self.unresolved)

    @property
    def non_fit_count(self) -> int:
        """Resolved accounts flagged below the ICP fit floor (D6 — surfaced to keep/drop)."""
        return sum(1 for a in self.resolved if a.fit_flag is FitFlag.NON_FIT)
