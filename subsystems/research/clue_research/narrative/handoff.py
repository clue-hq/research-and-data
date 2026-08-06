"""M12.2 — the ``account_handoff`` assembler + provenance index (the output edge).

The four required outputs (overview §1) live across the substrate as claims: the decomposed
fit/intent **scores** (M6.3, on the reserved ``account.scoring.*`` fields), the verified **account
profile** incl. ``account.resonance.*`` (M8.1/M8.2), the identity-resolved, governed **committee**
(M8.3/M8.4 × M10) and the per-``(account, persona)`` **value narrative** (M12.1). This module is the
**deterministic assembler/serializer** gathering the current verified truth into the one canonical
:class:`~clue_core.handoff.AccountHandoff` (conventions §4 / overview §3), with a
``provenance_index`` that makes "every fact links to its source" literally true and traversable.

Like ``current_value`` (substrate §1) it is a **pure function over the claim store** — no LLM, no
synthesis, no write to the domain — so the handoff is reproducible and auditable (AC5). It reads:

* **scores** via :func:`claims_for` on ``account.scoring.fit`` / ``.intent``, filtered to *this* ICP
  (an account scored under several ICPs has one live score per ICP — D5 — so the merge would mix
  them; the assembler keys on the score's ``value_json.icp_version``) → reconstructs the decomposed
  :class:`~clue_core.handoff.Score`, each sub-component carrying its evidence claim ids;
* the **account profile** as the verified ``current_values`` of every registered account-axis field
  (no hardcode — :func:`list_fields`), minus ``account.scoring.*`` (Output 1) and
  ``account.value_narrative`` (Output 4);
* the **committee** via the injected
  :class:`~clue_research.narrative.handoff_seams.HandoffCommitteeReader` (it cannot import
  ``profiling``/``compliance``), excluding weak-binding / use-disallowed facets from the
  outreach-eligible set (``is_outreach_promotable`` — Doc D / AC4);
* the **value narrative**: the *verified* ``account.value_narrative`` claims (M12.1) for this ICP +
  their ``claim_support`` two-sided provenance.

It then resolves **every** claim id appearing anywhere (score evidence, profile claims, committee
claims, narrative lines + their account-evidence support) to its source via :func:`claims_by_ids` —
a dangling reference is a **build failure** (:class:`HandoffAssemblyError`), never a silent omission
(AC2). Because the read is over ``current_value`` / live claims, a ``rejected`` claim is excluded by
construction (M13.1) and a re-assembly after supersession reflects the new truth (AC8).

``coverage_confidence`` (M6.5) and ``assembled_at`` are **injected** (the assembler stays a pure
store read and a worker — ``narrative`` may not import ``discovery_scoring``; and a deterministic
``assembled_at`` keeps two assembles byte-equal, AC5). The frozen ``AccountHandoff`` has no home
for the D6 non-fit flag or the M12.2 narrative judge citation, so those ride the
:class:`AssembledHandoff` wrapper (and the M12.2 materialization), never a ``core`` edit.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ACCOUNT_AXIS_FIELD_CLASSES,
    AccountHandoff,
    ClaimId,
    CommitteeMember,
    CurrentValue,
    EntityId,
    IdentityBinding,
    NarrativeSupport,
    Persona,
    ProfileClaimView,
    ProjectRunId,
    ProvenanceRef,
    Score,
    UnitInterval,
    UseClass,
    UtcDatetime,
    ValueNarrativeItem,
    VerificationStatus,
)
from clue_obs.otel import (
    ATTR_ENTITY_ID,
    ATTR_WORKSPACE_ID,
    MetricSink,
    apply_attributes,
    get_metric_sink,
    traced_step,
)
from clue_research.claimstore import (
    WorkspaceScope,
    claims_by_ids,
    claims_for,
    current_values,
    list_fields,
)
from clue_research.narrative.fields import VALUE_NARRATIVE
from clue_research.narrative.handoff_seams import HandoffCommitteeMember, HandoffCommitteeReader
from clue_research.narrative.health import VerificationHealth, compute_verification_health
from clue_research.narrative.support import (
    FaithfulnessCitation,
    read_claim_support,
    read_faithfulness_citations,
)

# The reserved Pass-A score fields (M6.3 ``discovery_scoring.scoring.engine`` writes them; that is a
# sibling worker ``narrative`` may not import, so the two stable reserved keys are re-declared —
# they are tenant-private, read under ``WorkspaceScope.for_workspace``).
FIT_FIELD = "account.scoring.fit"
INTENT_FIELD = "account.scoring.intent"

# The account-axis field classes whose verified current values are Output-2 profile claims (mirrors
# ``profiling.account._ACCOUNT_AXIS_CLASSES`` — ``narrative`` may not import ``profiling``).
# ``account.scoring.*`` (Output 1) and ``account.value_narrative`` (Output 4) classify as
# ``FieldClass.ACCOUNT`` but are *other* outputs and are excluded explicitly (the sharpest edge).
_ACCOUNT_AXIS_CLASSES = ACCOUNT_AXIS_FIELD_CLASSES
# The keys of ``core.handoff.Score`` (frozen, ``extra="forbid"``); the score ``value_json`` also
# carries reproducibility extras (``rubric_version`` / ``non_fit_flag`` / ``fit_floor`` / ``icp_*``)
# that must be stripped before ``Score.model_validate`` or it raises on the extras.
_SCORE_KEYS = ("value", "components")

SPAN_HANDOFF_ASSEMBLE = "narrative.handoff_assemble"
ATTR_N_PROFILE_CLAIMS = "narrative.handoff.n_profile_claims"
ATTR_N_COMMITTEE = "narrative.handoff.n_committee"
ATTR_N_NARRATIVE = "narrative.handoff.n_narrative"
ATTR_N_PROVENANCE = "narrative.handoff.n_provenance"
METRIC_HANDOFFS_ASSEMBLED = "research.handoff.assembled"


class HandoffAssemblyError(Exception):
    """A value in the assembled handoff points at a claim that does not resolve to a real,
    non-superseded, in-scope claim row — the "every line is sourced" invariant is broken, so the
    build fails loudly rather than emitting a handoff with a dangling provenance reference (AC2)."""


class AssembledHandoff(BaseModel):
    """The assembler's output: the frozen :class:`AccountHandoff` contract object (what M12.3 serves
    and M13 reviews) plus the M12.2-owned extras that have no home on the frozen contract —

    * ``non_fit`` (D6): the imported-account non-fit flag travels *with* the fit score; the frozen
      ``AccountHandoff`` has no field for it, so it is surfaced here (and in the materialization).
    * ``fit_scored`` / ``intent_scored``: whether a real score claim was found for this segment. The
      frozen ``AccountHandoff.fit_score`` / ``intent_score`` are non-optional, so a *missing* score
      is carried as an empty ``Score(value=0.0)`` placeholder — these flags make "unscored" explicit
      so a consumer never mistakes the placeholder for a real 0.0 fit ("no score without evidence").
    * ``narrative_citations``: per value-narrative ``claim_id``, "judged faithful by
      ``<answering_model>@<prompt_version>``" (the [M9.3×M12] answering-model citation) — the frozen
      ``ProvenanceRef`` carries no model, so the citation rides here.
    * ``coverage_gap_personas``: committee personas with no live, verified narrative claim — the
      M12.1 thin-coverage signal, surfaced explicitly (Doc C §7 coverage confidence).
    * ``verification_health`` (M12.3): the trust posture that travels with the served object (Doc C
      §6) — tier-4 judge pass rate + strong-binding share. Computed at assembly time over the
      *unfiltered* committee (the only place with the honest strong-binding denominator), so it has
      no
      home on the frozen contract; defaulted ``None`` so a pre-M12.3 materialised row still
      validates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    handoff: AccountHandoff
    non_fit: bool = False
    fit_scored: bool = True
    intent_scored: bool = True
    narrative_citations: dict[str, FaithfulnessCitation] = {}
    coverage_gap_personas: tuple[Persona, ...] = ()
    verification_health: VerificationHealth | None = None


# --- pure helpers (DB-free, unit-testable) ----------------------------------


def _score_from_value_json(value_json: JsonValue) -> tuple[Score, bool]:
    """Rebuild a :class:`core.handoff.Score` from a score claim's ``value_json`` and read the D6
    non-fit flag. The payload is the ``Score`` dump (``{value, components}``) plus flat extras
    (``rubric_version`` / ``non_fit_flag`` / ``fit_floor`` / ``icp_*``); ``Score`` is
    ``extra="forbid"`` so the extras are stripped before validation. ``non_fit_flag`` is a Fit-only
    extra (absent on the intent payload), defaulting ``False``."""
    payload = dict(value_json) if isinstance(value_json, dict) else {}
    score = Score.model_validate({k: payload[k] for k in _SCORE_KEYS if k in payload})
    return score, bool(payload.get("non_fit_flag", False))


def _profile_view(cv: CurrentValue) -> ProfileClaimView:
    """An account-profile :class:`ProfileClaimView` from a verified ``current_value`` — value + the
    winning provenance that proves it. ``identity_binding`` / ``use_class`` stay ``None`` (account
    claims are not governed-personal; only contact claims carry them)."""
    return ProfileClaimView(
        claim_id=cv.provenance.claim_id,
        value_json=cv.value_json,
        evidence_span=cv.provenance.evidence_span,
        source_tier=cv.provenance.source_tier,
    )


def _facet_outreach_eligible(pv: ProfileClaimView, decision_usable: bool) -> bool:
    """Whether a governed facet :class:`ProfileClaimView` may appear in the outreach-eligible
    committee set: strong identity-binding AND the M10 use-gate allowed it. Mirrors
    :func:`core.is_outreach_promotable` — which takes a ``Claim`` (it reads
    ``claim.identity_binding`` + the ``UseDecision``); a ``ProfileClaimView`` is not a ``Claim``, so
    the same two-axis predicate is applied to the view's ``identity_binding`` and the decision's
    ``usable_for_outreach``."""
    return pv.identity_binding is IdentityBinding.STRONG and decision_usable


def _filter_committee_member(hm: HandoffCommitteeMember) -> CommitteeMember:
    """Project a :class:`HandoffCommitteeMember` to the handoff :class:`CommitteeMember`, dropping
    weak-binding / use-disallowed facet profile claims from the outreach-eligible set (M12.2 AC4) —
    **fail-closed** on personal data.

    A profile claim with a ``use_decisions`` entry was evaluated by the M10 use-gate → kept only if
    it clears both gates (``is_outreach_promotable``: strong binding AND use-allowed). A claim with
    **no** decision is gate-*un*evaluated; the production seam (``build_handoff_skeleton``) fills
    ``profile_claims`` from M8.4 contact-fill outputs, which are mostly governed ``contact.facet.*``
    hooks, so a missing decision must NOT default-keep a personal hook into outreach. So a
    no-decision
    claim is kept only when it is **not** a governed-personal class — ``use_class`` is ``None`` or
    ``PROFESSIONAL_PUBLIC`` (an identifying / professional view, e.g. role, title); a no-decision
    ``SENSITIVE`` or ``PERSONAL_PUBLIC_NON_SENSITIVE`` claim is dropped (fail-closed: a personal
    hook
    never crosses ungated)."""
    kept: list[ProfileClaimView] = []
    for pv in hm.member.profile_claims:
        decision = hm.use_decisions.get(pv.claim_id)
        if decision is not None:
            if _facet_outreach_eligible(pv, decision.usable_for_outreach):
                kept.append(pv)  # governed facet that cleared both gates
            # else: weak-binding or use-disallowed facet → excluded (AC4)
        elif pv.use_class is None or pv.use_class is UseClass.PROFESSIONAL_PUBLIC:
            kept.append(pv)  # identifying / professional-public view (not a gated personal hook)
        # else: a governed-personal claim (SENSITIVE / PERSONAL_PUBLIC_NON_SENSITIVE) with no
        # use-gate
        #       verdict → dropped (fail-closed; never cross a personal hook ungated)
    kept.sort(key=lambda pv: (str(pv.value_json), str(pv.claim_id)))  # AC5 byte-stability
    return hm.member.model_copy(update={"profile_claims": tuple(kept)})


class HandoffAssembler:
    """The M12.2 ``account_handoff`` assembler. Constructed with the injected
    :class:`HandoffCommitteeReader` at the ``api`` composition root; :meth:`assemble` is a pure,
    deterministic read over the claim store (no LLM, no write — AC5)."""

    def __init__(
        self,
        *,
        committee_reader: HandoffCommitteeReader,
        sink: MetricSink | None = None,
    ) -> None:
        self._committee_reader = committee_reader
        self._sink = sink

    async def assemble(
        self,
        conn: AsyncConnection,
        account_entity_id: EntityId,
        *,
        icp_spec_version: int,
        workspace_id: str,
        assembled_at: UtcDatetime,
        icp_key: str | None = None,
        project_run_id: ProjectRunId | None = None,
        coverage_confidence: UnitInterval | None = None,
        product_id: str | None = None,
    ) -> AssembledHandoff:
        """Assemble the ``account_handoff`` for one ``(account_entity_id, icp_spec_version)``.

        ``workspace_id`` is the workspace whose view this is (scores / resonance / narrative /
        committee
        are ``TENANT_PRIVATE``); reads are scoped to ``WorkspaceScope.for_workspace(workspace_id)``
        so a
        cross-tenant claim never enters the handoff. ``assembled_at`` + ``coverage_confidence`` are
        injected (a deterministic stamp keeps re-assembly byte-stable; M6.5 coverage is a sibling
        worker's output).

        ``icp_key`` disambiguates the ICP **segment**: an ICP is ``(workspace_id, icp_key,
        version)``
        and ``version`` restarts at 1 per ``icp_key`` (D5), so two segments can share
        ``icp_spec_version=1``. When the account is targeted under several segments the production
        caller MUST pass ``icp_key`` — the scores and narrative are then matched on *both*
        ``icp_key`` and ``icp_spec_version`` so segment A's handoff never mixes in segment B's score
        or narrative. ``None`` (a single-segment account) matches on the version alone (legacy).

        Raises :class:`HandoffAssemblyError` if any value's claim id is unresolvable (the build-fail
        "every line is sourced" check)."""
        scope = WorkspaceScope.for_workspace(workspace_id)
        with traced_step(
            SPAN_HANDOFF_ASSEMBLE,
            **{ATTR_ENTITY_ID: str(account_entity_id), ATTR_WORKSPACE_ID: workspace_id},
        ) as span:
            # 1) decomposed scores for THIS segment (D5: version restarts per icp_key, so match
            # both).
            fit_score, non_fit, fit_scored = await self._read_score(
                conn,
                account_entity_id,
                FIT_FIELD,
                icp_spec_version,
                icp_key,
                product_id,
                project_run_id,
                scope,
            )
            intent_score, _, intent_scored = await self._read_score(
                conn,
                account_entity_id,
                INTENT_FIELD,
                icp_spec_version,
                icp_key,
                product_id,
                project_run_id,
                scope,
            )

            # 2) verified account profile claims (Output 2) + the field-conflict surface.
            profile_claims, field_conflicts = await self._read_account_profile(
                conn, account_entity_id, product_id, scope
            )

            # 3) the governed committee (Output 3) — weak/disallowed facets excluded (AC4). Sorted
            #    by (persona, contact) so the handoff is byte-stable independent of the seam's read
            #    order (AC5 determinism), not relying on the deferred production reader to order.
            hand_members = await self._committee_reader.committee_for_handoff(
                account_entity_id=account_entity_id, workspace_id=workspace_id
            )
            committee = tuple(
                sorted(
                    (_filter_committee_member(hm) for hm in hand_members),
                    key=lambda m: (m.persona.value, str(m.contact_entity_id)),
                )
            )

            # 4) the value narrative (Output 4) for THIS segment + its judge citations + coverage
            # gaps.
            narrative, citations = await self._read_value_narrative(
                conn, account_entity_id, icp_spec_version, icp_key, product_id, scope
            )
            personas_with_narrative = {item.persona for item in narrative}
            coverage_gaps = tuple(
                sorted(
                    {m.persona for m in committee} - personas_with_narrative,
                    key=lambda p: p.value,
                )
            )

            # 5) provenance index over every claim id that appears — build-fails on a dangling ref.
            provenance = await self._build_provenance_index(
                conn,
                scope,
                fit_score=fit_score,
                intent_score=intent_score,
                profile_claims=profile_claims,
                committee=committee,
                narrative=narrative,
                field_conflicts=field_conflicts,
            )

            handoff = AccountHandoff(
                account_entity_id=account_entity_id,
                fit_score=fit_score,
                intent_score=intent_score,
                account_profile_claims=profile_claims,
                committee=committee,
                value_narrative=narrative,
                provenance_index=provenance,
                icp_spec_version=icp_spec_version,
                project_run_id=project_run_id,
                assembled_at=assembled_at,
                coverage_confidence=coverage_confidence,
                field_conflicts=field_conflicts,
            )
            apply_attributes(
                span,
                {
                    ATTR_N_PROFILE_CLAIMS: len(profile_claims),
                    ATTR_N_COMMITTEE: len(committee),
                    ATTR_N_NARRATIVE: len(narrative),
                    ATTR_N_PROVENANCE: len(provenance),
                },
            )
            # 6) verification health (Doc C §6) over the UNFILTERED committee + narrative citations
            # —
            #    the honest strong-binding denominator (the handoff's committee is post-filter).
            # Pure
            #    + deterministic, so it keeps re-assembly byte-stable (AC5).
            health = compute_verification_health(
                narrative=narrative,
                citations=citations,
                committee_members=hand_members,
            )
            (self._sink or get_metric_sink()).add(METRIC_HANDOFFS_ASSEMBLED, 1, {})
            return AssembledHandoff(
                handoff=handoff,
                non_fit=non_fit,
                fit_scored=fit_scored,
                intent_scored=intent_scored,
                narrative_citations=citations,
                coverage_gap_personas=coverage_gaps,
                verification_health=health,
            )

    async def _read_score(
        self,
        conn: AsyncConnection,
        account_entity_id: EntityId,
        field_key: str,
        icp_spec_version: int,
        icp_key: str | None,
        product_id: str | None,
        project_run_id: ProjectRunId | None,
        scope: WorkspaceScope,
    ) -> tuple[Score, bool, bool]:
        """The decomposed score for *this* ICP segment. Filters the live ``account.scoring.*``
        claims
        by ``value_json.icp_version`` **and** ``icp_key`` (D5: version restarts per ``icp_key``, so
        version alone would mix two segments' live scores). Returns ``(score, non_fit_flag,
        scored)``
        — ``scored`` is ``False`` and the ``Score`` is the empty placeholder ``value=0.0`` when the
        account carries no matching score (the absence is surfaced explicitly on the wrapper rather
        than fabricating a real 0.0 fit — "no score without its evidence")."""
        claims = await claims_for(conn, account_entity_id, field_key, scope=scope)
        for claim in claims:  # claims_for orders collected_at DESC → most recent first
            value = claim.value_json
            if (
                isinstance(value, dict)
                and value.get("icp_version") == icp_spec_version
                and (icp_key is None or value.get("icp_key") == icp_key)
                and claim.product_id == product_id
                and (project_run_id is None or value.get("project_run_id") == str(project_run_id))
            ):
                score, non_fit = _score_from_value_json(value)
                return score, non_fit, True
        return Score(value=0.0), False, False

    async def _read_account_profile(
        self,
        conn: AsyncConnection,
        account_entity_id: EntityId,
        product_id: str | None,
        scope: WorkspaceScope,
    ) -> tuple[tuple[ProfileClaimView, ...], dict[str, tuple[ClaimId, ...]]]:
        """The verified account profile claims (Output 2) + the per-field conflict surface.

        Enumerates the account-axis fields generically (no hardcode — :func:`list_fields`),
        drops ``account.scoring.*`` (Output 1) and ``account.value_narrative`` (Output 4), and reads
        their verified ``current_values`` in one batch (the merge excludes unverified-tier4 /
        rejected / superseded / weak-binding / tombstoned claims, so "verified-only" is free). A
        a ``current_value`` conflict (two tier≤2 sources disagree under the ``equality_mode`` —
        now mode-aware per [M9.2×M1.2]) propagates into ``field_conflicts`` (Doc C §7)."""
        fields = await list_fields(conn, active=True)
        profile_field_keys = [
            f.field_key
            for f in fields
            if f.field_class in _ACCOUNT_AXIS_CLASSES
            and not f.field_key.startswith("account.scoring.")
            and f.field_key != VALUE_NARRATIVE
        ]
        merged = await current_values(conn, [account_entity_id], profile_field_keys, scope=scope)

        views: list[ProfileClaimView] = []
        field_conflicts: dict[str, tuple[ClaimId, ...]] = {}
        for (entity_id, field_key), cv in merged.items():
            if entity_id != account_entity_id:
                continue
            winning = await claims_by_ids(
                conn,
                (cv.provenance.claim_id,),
                scope=scope,
            )
            winner = winning.get(cv.provenance.claim_id)
            if winner is None:
                continue
            # Target-account facts may be product-neutral. A product-scoped fact is visible only
            # for its exact product; a no-product request cannot absorb a product-specific value.
            if winner.product_id is not None and winner.product_id != product_id:
                continue
            views.append(_profile_view(cv))
            if cv.conflict and cv.conflicting_claim_ids:
                field_conflicts[field_key] = cv.conflicting_claim_ids
        views.sort(key=lambda v: (str(v.value_json), str(v.claim_id)))
        return tuple(views), dict(sorted(field_conflicts.items()))

    async def _read_value_narrative(
        self,
        conn: AsyncConnection,
        account_entity_id: EntityId,
        icp_spec_version: int,
        icp_key: str | None,
        product_id: str | None,
        scope: WorkspaceScope,
    ) -> tuple[tuple[ValueNarrativeItem, ...], dict[str, FaithfulnessCitation]]:
        """The verified value-narrative lines (Output 4) for this ICP segment + their judge
        citations.

        Matched on ``icp_spec_version`` **and** ``icp_key`` (D5: version restarts per segment, so
        version alone would mix segment A's and B's narratives). Only **verified**
        ``account.value_narrative`` claims belong in the handoff: an ungrounded argument is
        ``rejected`` by the M9.3 judge and must not appear. Each line carries its two-sided
        ``claim_support`` (account evidence × client knowledge) and, in the wrapper's
        ``narrative_citations``, the answering judge model ([M9.3×M12]). Ordered by ``(persona,
        claim_id)`` for a byte-stable handoff (AC5)."""
        claims = await claims_for(conn, account_entity_id, VALUE_NARRATIVE, scope=scope)
        items: list[ValueNarrativeItem] = []
        citation_claims = []
        for claim in claims:
            value = claim.value_json
            if not isinstance(value, dict):
                continue
            if value.get("icp_spec_version") != icp_spec_version:
                continue
            if icp_key is not None and value.get("icp_key") != icp_key:
                continue  # a different ICP segment (D5)
            if claim.product_id != product_id:
                continue  # product-scoped narrative relevance is exact, never inherited
            if claim.verification_status is not VerificationStatus.VERIFIED:
                continue  # an ungrounded / unpromoted narrative is not handed off
            support = await read_claim_support(conn, claim.id)
            items.append(
                ValueNarrativeItem(
                    claim_id=claim.id,
                    persona=Persona(str(value["persona"])),
                    argument=str(value.get("argument", "")),
                    supporting=NarrativeSupport(
                        account_evidence_ids=(
                            support.account_evidence_ids if support is not None else ()
                        ),
                        client_knowledge_ids=(
                            support.client_knowledge_ids if support is not None else ()
                        ),
                    ),
                )
            )
            citation_claims.append(claim)
        citations = {
            str(claim_id): citation
            for claim_id, citation in (
                await read_faithfulness_citations(conn, citation_claims)
            ).items()
        }
        items.sort(key=lambda i: (i.persona.value, str(i.claim_id)))
        return tuple(items), dict(sorted(citations.items()))

    async def _build_provenance_index(
        self,
        conn: AsyncConnection,
        scope: WorkspaceScope,
        *,
        fit_score: Score,
        intent_score: Score,
        profile_claims: tuple[ProfileClaimView, ...],
        committee: tuple[CommitteeMember, ...],
        narrative: tuple[ValueNarrativeItem, ...],
        field_conflicts: dict[str, tuple[ClaimId, ...]],
    ) -> dict[str, ProvenanceRef]:
        """Resolve **every** claim id appearing anywhere to its (immutable) source provenance — the
        literal "every fact links to its source" map (overview §3, AC2). Collects: each score
        sub-component's ``evidence_claim_ids``; each account-profile claim id; each committee
        ``profile_claim`` id (only the *included*, outreach-eligible ones — an excluded
        weak/disallowed facet is absent from the handoff AND the index — M13.1); each narrative id
        and its account-evidence support ids; each ``field_conflicts`` contender id (the disagreeing
        tier≤2 claims surfaced on the handoff are themselves traceable).

        A current-truth **value** (a profile / committee / narrative claim) is non-superseded by
        construction — it was read via ``current_value`` / the seam / live ``claims_for``. A
        derivation-evidence **reference** (a score sub-component's signal, a narrative's cited
        account evidence) is resolved even if it has since been *superseded* (e.g. a refreshed
        signal that did not trigger a re-score): its ``source_url`` / ``source_tier`` /
        ``evidence_span`` are immutable, so the citation stays traceable rather than permanently
        breaking the build. Only a **truly non-existent / out-of-scope** id (never inserted, or
        another tenant's) is a dangling reference → :class:`HandoffAssemblyError` (never a silent
        drop)."""
        ids: set[ClaimId] = set()
        for score in (fit_score, intent_score):
            for comp in score.components:
                ids.update(comp.evidence_claim_ids)
        ids.update(pv.claim_id for pv in profile_claims)
        for member in committee:
            ids.update(pv.claim_id for pv in member.profile_claims)
        for item in narrative:
            ids.add(item.claim_id)
            ids.update(item.supporting.account_evidence_ids)
        for contender_ids in field_conflicts.values():
            ids.update(contender_ids)

        if not ids:
            return {}
        # include_superseded: a since-superseded *derivation-evidence* reference still resolves to
        # its immutable source (the value itself is live — read via current_value / the seam).
        resolved = await claims_by_ids(conn, ids, scope=scope, include_superseded=True)
        missing = ids - set(resolved.keys())
        if missing:
            joined = ", ".join(sorted(str(m) for m in missing))
            raise HandoffAssemblyError(
                f"account_handoff has values pointing at {len(missing)} unresolvable claim id(s) "
                f"(no real, in-scope claim — never inserted or out of tenant scope): {joined}"
            )
        return {
            str(cid): ProvenanceRef(
                source_url=claim.source_url,
                source_tier=claim.source_tier,
                evidence_span=claim.evidence_span,
            )
            for cid, claim in sorted(resolved.items(), key=lambda kv: str(kv[0]))
        }
