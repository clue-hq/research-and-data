"""ICP synthesis — candidate ICP proposals from the Client Knowledge Base (M5.2).

From the versioned Client Knowledge Base (M5.1), synthesize one or more **candidate ICPs** as
structured hypotheses (Doc B §3) — never prose — for the client to edit and confirm. Each proposal
carries all six Doc B §3 elements (firmographic, technographic/vertical, two-tier candidate signals,
seed accounts, starting source profile, scoring rubric) and every element links the **Client-KB
claim ids** that justify it (no element justified by "synthesis thought it was a good idea").

Synthesis reads **two evidence species, both reference-only**: the versioned Client-KB claims and
the project-scoped interview statements the client volunteered in conversation
(``volunteered_statement`` rows routed ``project_state`` — the caller supplies them as typed
:class:`ProjectStatement` inputs with the exact artifact-proven quote). Targeting the client stated
only in conversation therefore grounds the ICP without first having to become a Client-KB claim.
With **neither** species present the synthesis is honest about it: the result carries
``status=floor_only`` plus reason codes, and its single proposal is the explicitly-labelled,
citation-free config floor — a caller may render "not ready" instead of presenting it as a
grounded candidate (fabrication, not emptiness, is the failure).

The proposal-generation model is an LLM call through the shared
:class:`~clue_core.LLMGateway` (M0.4) — injected, **config-bounded** to the offered pack
catalog + the registered candidate field set (the model may rank/choose/split *within* the bounds
but can never name a field or pack outside them; off-set names are dropped, exactly like the M4.6
Source Planner). The LLM is **optional**: with no gateway the synthesis returns a deterministic
floor proposal derived straight from the Client KB
(the config is always the floor), so the no-LLM path still yields a complete proposal and tests stay
hermetic. Downstream consumes only the compiled ``ICPSpec`` (M5.2 confirm), never this proposal, so
the model is fully swappable behind the compiled-spec seam (conventions §2).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    ClaimId,
    FieldDef,
    LLMGateway,
    Message,
    PassKind,
    ReuseScope,
    Role,
    VolunteeredStatementId,
    classify_field_key,
    is_valid_field_key,
)
from clue_core.proposals import FieldProposalRef
from clue_research.claimstore import list_fields
from clue_research.icp import get_pack_field_set, get_pack_source_profile, list_packs
from clue_research.proposals import (
    FieldProposalPayload,
    ProposalScope,
    propose_field,
    reject_field_concept,
)
from clue_research.stage0.client_kb import read_client_kb_claims
from clue_research.stage0.fields import (
    CLIENT_DELIVERED_VALUE,
    CLIENT_DIFFERENTIATOR,
    CLIENT_ICP_EVIDENCE,
    CLIENT_PRODUCT,
    CLIENT_VALUE_PROP,
)
from clue_research.stage0.icp_types import (
    CandidateSignal,
    FirmographicDimensions,
    ICPProposal,
    ProposedRubric,
    RubricWeight,
    SourcePrior,
    StartingSourceProfile,
    TechnographicDimension,
)
from clue_research.stage0.types import ClientKnowledgeBaseRef

# Candidate INPUT fields exclude these namespaces: ``client.*``/``icp.*`` are client-knowledge /
# feedback (not account research fields), and ``account.scoring.*`` are the *outputs* M6 writes, not
# scoring inputs. Bounding to real registered fields is what keeps synthesis fabrication-proof.
_EXCLUDED_INPUT_PREFIXES = ("client.", "icp.", "account.scoring.")

# Floor priors: the cheap firmographic fields and the generic growth signal a thin KB can still
# anchor on. All are commodity ``core.*``/``account.*`` fields (present once the core pack loads).
_FLOOR_FIRMOGRAPHIC = ("core.employee_count", "core.primary_domain")
_FLOOR_GROWTH_PROXY = "account.recent_funding"
_FLOOR_GROWTH_NARRATIVE = "account.hiring_velocity_eng"

# Reason codes for a ``floor_only`` result — exactly the evidence species that were missing.
NO_CLIENT_KB_CLAIMS = "no_client_kb_claims"
NO_PROJECT_STATEMENTS = "no_project_statements"

_UNGROUNDED_LABEL = "Ungrounded baseline (no evidence)"
_UNGROUNDED_RATIONALE = (
    "No Client-KB claims and no project statements were available, so this baseline cites no "
    "evidence. It is the config floor, not a grounded ICP candidate."
)
_GROUNDED_RATIONALE = (
    "Deterministic floor proposal derived from the Client Knowledge Base and project statements."
)


class ProjectStatement(BaseModel):
    """One project-scoped interview statement offered to synthesis as evidence.

    ``statement_id`` is the durable ``volunteered_statement`` id the proposal cites (lineage is
    reference-only). ``quote`` is the exact span the caller resolved from the statement's captured
    onboarding artifact — it is prompt/matching *input*, never copied into the proposal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    statement_id: VolunteeredStatementId
    route_key: str
    quote: str


class ICPSynthesisStatus(StrEnum):
    """Whether the synthesis had anything to ground on.

    ``GROUNDED`` — at least one evidence reference existed (Client-KB claims and/or project
    statements), so every emitted element cites real ids. This says nothing about *which* generator
    ran: a config-floor proposal over a real Client KB is still grounded.

    ``FLOOR_ONLY`` — there was no evidence at all; the single proposal is the citation-free config
    floor and the caller should surface "not ready", not a candidate ICP."""

    GROUNDED = "grounded"
    FLOOR_ONLY = "floor_only"


class ICPSynthesisResult(BaseModel):
    """Co-confirmation payload: bounded ICP candidates plus preserved new-concept references.

    ``proposals`` always holds ≥1 complete proposal (the config is always the floor), so a
    production caller never has to handle "no proposal"; ``status``/``reason_codes`` say whether
    that proposal is allowed to be presented as grounded."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposals: tuple[ICPProposal, ...]
    status: ICPSynthesisStatus
    reason_codes: tuple[str, ...] = ()
    field_proposal_refs: tuple[FieldProposalRef, ...] = ()


@dataclass(frozen=True, slots=True)
class _RejectedConcept:
    raw_input: JsonValue
    reason: str


async def synthesize_icps(
    conn: AsyncConnection,
    client_kb_ref: ClientKnowledgeBaseRef,
    *,
    workspace_id: str,
    project_statements: tuple[ProjectStatement, ...] = (),
    gateway: LLMGateway | None = None,
    synthesis_model: str | None = None,
) -> ICPSynthesisResult:
    """Synthesize ≥1 candidate :class:`ICPProposal` from the client's Knowledge Base + statements.

    Reads the Client KB at ``client_kb_ref.client_kb_version`` (the version-correct read — M5.1) and
    takes the project's ``project_statements`` (Stage-0 ``project_state`` interview statements) as
    the second evidence species, so each proposed element can cite the claim ids **and** statement
    ids behind it. With ``gateway`` + ``synthesis_model`` set, an LLM proposes structure (and may
    split into multiple ICPs when customer evidence clusters — D5), **bounded** to the offered packs
    + registered fields; any out-of-bounds name is dropped. With no gateway (or on any LLM/parse
    failure), a deterministic floor proposal is returned — there is always ≥1 complete proposal.
    When neither evidence species is present the result's ``status`` is
    :attr:`ICPSynthesisStatus.FLOOR_ONLY` and the floor proposal is explicitly labelled ungrounded.
    The synthesis never resolves names or runs discovery: seed accounts are supplied by M5.4
    downstream (empty in the floor)."""
    return await _synthesize(
        conn,
        client_kb_ref,
        workspace_id=workspace_id,
        project_statements=project_statements,
        gateway=gateway,
        synthesis_model=synthesis_model,
        proposal_scope=None,
        proposed_by_actor="system",
        proposed_by_ref=None,
    )


async def synthesize_icps_with_proposals(
    conn: AsyncConnection,
    client_kb_ref: ClientKnowledgeBaseRef,
    *,
    workspace_id: str,
    proposal_scope: ProposalScope,
    proposed_by_actor: str,
    proposed_by_ref: str | None = None,
    project_statements: tuple[ProjectStatement, ...] = (),
    gateway: LLMGateway | None = None,
    synthesis_model: str | None = None,
) -> ICPSynthesisResult:
    """Open-schema synthesis for C4: unknown concepts become scoped proposal references."""
    if proposal_scope.workspace_id != workspace_id:
        raise ValueError("proposal_scope must belong to the synthesis workspace")
    return await _synthesize(
        conn,
        client_kb_ref,
        workspace_id=workspace_id,
        project_statements=project_statements,
        gateway=gateway,
        synthesis_model=synthesis_model,
        proposal_scope=proposal_scope,
        proposed_by_actor=proposed_by_actor,
        proposed_by_ref=proposed_by_ref,
    )


async def _synthesize(
    conn: AsyncConnection,
    client_kb_ref: ClientKnowledgeBaseRef,
    *,
    workspace_id: str,
    project_statements: tuple[ProjectStatement, ...],
    gateway: LLMGateway | None,
    synthesis_model: str | None,
    proposal_scope: ProposalScope | None,
    proposed_by_actor: str,
    proposed_by_ref: str | None,
) -> ICPSynthesisResult:
    kb_claims = await read_client_kb_claims(
        conn,
        client_kb_ref.client_entity_id,
        workspace_id=workspace_id,
        version=client_kb_ref.client_kb_version,
        product_id=client_kb_ref.product_id,
    )
    statement_ids = tuple(item.statement_id for item in project_statements)
    reason_codes = tuple(
        code
        for code, missing in (
            (NO_CLIENT_KB_CLAIMS, not kb_claims),
            (NO_PROJECT_STATEMENTS, not project_statements),
        )
        if missing
    )
    grounded = bool(kb_claims) or bool(project_statements)

    scoring_keys, deep_keys = await _candidate_field_keys(conn)
    pack_field_keys, pack_priors = await _pack_offerings(conn)

    used_llm = gateway is not None and synthesis_model is not None
    field_payloads: tuple[FieldProposalPayload, ...] = ()
    rejected_concepts: tuple[_RejectedConcept, ...] = ()
    if used_llm:
        assert gateway is not None and synthesis_model is not None  # narrowed by used_llm
        proposals, field_payloads, rejected_concepts = _proposals_from_llm(
            gateway,
            synthesis_model,
            kb_claims,
            project_statements,
            scoring_keys=scoring_keys,
            deep_keys=deep_keys,
            pack_field_keys=pack_field_keys,
            pack_priors=pack_priors,
        )
    else:
        proposals = []
    if not proposals:
        proposals = [
            _floor_proposal(
                kb_claims,
                statement_ids=statement_ids,
                statement_quotes=tuple(item.quote for item in project_statements),
                grounded=grounded,
                scoring_keys=scoring_keys,
                deep_keys=deep_keys,
                pack_field_keys=pack_field_keys,
                pack_priors=pack_priors,
            )
        ]

    refs: list[FieldProposalRef] = []
    if proposal_scope is not None:
        for payload in field_payloads:
            proposal = await propose_field(
                conn,
                scope=proposal_scope,
                payload=payload,
                proposed_by_actor=proposed_by_actor,
                proposed_by_ref=proposed_by_ref,
            )
            refs.append(
                FieldProposalRef(
                    proposal_id=proposal.id,
                    field_key=proposal.payload.field_def.field_key,
                    status=proposal.status,
                )
            )
        evidence_refs = tuple(str(claim.id) for claim in kb_claims.values())
        for rejected in rejected_concepts:
            proposal = await reject_field_concept(
                conn,
                scope=proposal_scope,
                raw_input=rejected.raw_input,
                reason=rejected.reason,
                proposed_by_actor=proposed_by_actor,
                proposed_by_ref=proposed_by_ref,
                evidence_refs=evidence_refs,
            )
            refs.append(
                FieldProposalRef(
                    proposal_id=proposal.id,
                    field_key=proposal.payload.field_def.field_key,
                    status=proposal.status,
                )
            )
    return ICPSynthesisResult(
        proposals=tuple(proposals),
        status=ICPSynthesisStatus.GROUNDED if grounded else ICPSynthesisStatus.FLOOR_ONLY,
        reason_codes=reason_codes,
        field_proposal_refs=tuple(refs),
    )


# --- offered bounds (config-bounding the synthesis) -------------------------


async def _candidate_field_keys(conn: AsyncConnection) -> tuple[frozenset[str], frozenset[str]]:
    """The registered (scoring, deep) field-key sets the synthesis may choose from — every
    Pass-A/Pass-B research field except the client-knowledge / feedback / score-output classes."""
    scoring = frozenset(
        f.field_key
        for f in await list_fields(conn, pass_kind=PassKind.SCORING)
        if not f.field_key.startswith(_EXCLUDED_INPUT_PREFIXES)
    )
    deep = frozenset(
        f.field_key
        for f in await list_fields(conn, pass_kind=PassKind.DEEP)
        if not f.field_key.startswith(_EXCLUDED_INPUT_PREFIXES)
    )
    return scoring, deep


async def _pack_offerings(
    conn: AsyncConnection,
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[SourcePrior, ...]]]:
    """Per registered pack: its ``<pack>.*`` field keys and its flattened source priors (the
    starting source profile preview). The catalog of vertical dimensions synthesis may enable."""
    field_keys: dict[str, tuple[str, ...]] = {}
    priors: dict[str, tuple[SourcePrior, ...]] = {}
    for record in await list_packs(conn):
        pack_key = record.pack_key
        fields = await get_pack_field_set(conn, pack_key)
        field_keys[pack_key] = tuple(f.field_key for f in fields)
        profile = await get_pack_source_profile(conn, pack_key)
        priors[pack_key] = tuple(
            SourcePrior(source_key=ws.source_key, weight=ws.weight.value, rank=ws.rank)
            for ws in profile.default
        )
    return field_keys, priors


# --- justification (real Client-KB claim ids, never invented) ---------------


def _justifier(kb_claims: dict[str, Claim]) -> tuple[dict[str, ClaimId], tuple[ClaimId, ...]]:
    by_field = {fk: claim.id for fk, claim in kb_claims.items()}
    return by_field, tuple(by_field.values())


def _justify(
    source_fields: tuple[str, ...],
    by_field: dict[str, ClaimId],
    all_ids: tuple[ClaimId, ...],
) -> tuple[ClaimId, ...]:
    """The claim ids justifying an element: the specific client fields it drew on (when present),
    else the whole read set — always **real** ids (empty only when the KB itself is empty)."""
    specific = tuple(by_field[fk] for fk in source_fields if fk in by_field)
    return specific or all_ids


# --- deterministic floor ----------------------------------------------------


def _floor_proposal(
    kb_claims: dict[str, Claim],
    *,
    statement_ids: tuple[VolunteeredStatementId, ...],
    statement_quotes: tuple[str, ...],
    grounded: bool,
    scoring_keys: frozenset[str],
    deep_keys: frozenset[str],
    pack_field_keys: dict[str, tuple[str, ...]],
    pack_priors: dict[str, tuple[SourcePrior, ...]],
) -> ICPProposal:
    """The config floor: one ICP straight from the Client KB + project statements. A vertical pack
    is chosen by matching the pack's namespace tokens against the client's own prose (value prop /
    product / reviews) and the statements' quotes; the rubric scores presence of the firmographic +
    growth-proxy fields. Honest about thinness — a field or pack with no support is simply absent,
    never fabricated, and with no evidence at all the proposal is labelled ungrounded and cites
    nothing."""
    by_field, all_ids = _justifier(kb_claims)

    firmo_keys = tuple(k for k in _FLOOR_FIRMOGRAPHIC if k in scoring_keys)
    evidence = kb_claims.get(CLIENT_ICP_EVIDENCE)
    firmographic = FirmographicDimensions(
        industry=_evidence_str(evidence, "industries"),
        size_band=_evidence_str(evidence, "sizes"),
        geo=_evidence_str(evidence, "geos"),
        field_keys=firmo_keys,
        justifying_claim_ids=_justify((CLIENT_ICP_EVIDENCE,), by_field, all_ids),
        justifying_statement_ids=statement_ids,
    )

    pack_key = _match_pack(kb_claims, statement_quotes, pack_field_keys)
    technographic = (
        tuple(
            TechnographicDimension(
                field_key=fk,
                pack_key=pack_key,
                justifying_claim_ids=_justify(
                    (CLIENT_PRODUCT, CLIENT_VALUE_PROP, CLIENT_DIFFERENTIATOR), by_field, all_ids
                ),
                justifying_statement_ids=statement_ids,
            )
            for fk in pack_field_keys.get(pack_key, ())
        )
        if pack_key is not None
        else ()
    )

    signals: list[CandidateSignal] = []
    growth_proxy = (_FLOOR_GROWTH_PROXY,) if _FLOOR_GROWTH_PROXY in scoring_keys else ()
    growth_narrative = (_FLOOR_GROWTH_NARRATIVE,) if _FLOOR_GROWTH_NARRATIVE in deep_keys else ()
    if growth_proxy or growth_narrative:
        signals.append(
            CandidateSignal(
                signal_class="growth",
                proxy_field_keys=growth_proxy,
                narrative_field_keys=growth_narrative,
                justifying_claim_ids=_justify(
                    (CLIENT_DELIVERED_VALUE, CLIENT_ICP_EVIDENCE), by_field, all_ids
                ),
                justifying_statement_ids=statement_ids,
            )
        )
    if pack_key is not None:
        pack_proxy = tuple(k for k in pack_field_keys.get(pack_key, ()) if k in scoring_keys)
        pack_narr = tuple(k for k in pack_field_keys.get(pack_key, ()) if k in deep_keys)
        if pack_proxy or pack_narr:
            signals.append(
                CandidateSignal(
                    signal_class=f"{pack_key}_vertical",
                    proxy_field_keys=pack_proxy,
                    narrative_field_keys=pack_narr,
                    justifying_claim_ids=_justify(
                        (CLIENT_PRODUCT, CLIENT_VALUE_PROP), by_field, all_ids
                    ),
                    justifying_statement_ids=statement_ids,
                )
            )

    packs = (pack_key,) if pack_key is not None else ()
    source_profile = StartingSourceProfile(
        packs=packs,
        priors=tuple(p for pk in packs for p in pack_priors.get(pk, ())),
        justifying_claim_ids=all_ids,
        justifying_statement_ids=statement_ids,
    )

    rubric = _floor_rubric(firmo_keys, growth_proxy, all_ids, statement_ids)

    return ICPProposal(
        icp_key="primary",
        label="Primary ICP (synthesized)" if grounded else _UNGROUNDED_LABEL,
        rationale=_GROUNDED_RATIONALE if grounded else _UNGROUNDED_RATIONALE,
        firmographic=firmographic,
        technographic=technographic,
        candidate_signals=tuple(signals),
        seed_accounts=(),  # seeds are assembled + resolved by M5.4 (never free-text here)
        source_profile=source_profile,
        rubric=rubric,
        justifying_claim_ids=all_ids,
        justifying_statement_ids=statement_ids,
    )


def _floor_rubric(
    firmo_keys: tuple[str, ...],
    growth_proxy: tuple[str, ...],
    all_ids: tuple[ClaimId, ...],
    statement_ids: tuple[VolunteeredStatementId, ...],
) -> ProposedRubric:
    """A minimal fit + intent rubric over Pass-A scoring fields (presence-based; the client refines
    weights/transforms on edit). Every entry references a scoring field, so it survives
    ``validate_rubric`` at confirm."""
    fit = tuple(
        RubricWeight(
            field_key=fk,
            dimension="fit",
            justifying_claim_ids=all_ids,
            justifying_statement_ids=statement_ids,
        )
        for fk in firmo_keys
    )
    intent = tuple(
        RubricWeight(
            field_key=fk,
            dimension="intent",
            justifying_claim_ids=all_ids,
            justifying_statement_ids=statement_ids,
        )
        for fk in growth_proxy
    )
    return ProposedRubric(weights=fit + intent, fit_threshold=0.5, intent_threshold=0.3)


def _evidence_str(claim: Claim | None, key: str) -> str | None:
    """First value of ``claim.value_json[key]`` (an ICP-evidence object's industries/sizes/geos), or
    ``None``. Best-effort over loosely-typed client evidence — never raises."""
    if claim is None or not isinstance(claim.value_json, dict):
        return None
    value = claim.value_json.get(key)
    if isinstance(value, list) and value and isinstance(value[0], str) and value[0]:
        return value[0]
    if isinstance(value, str) and value:
        return value
    return None


_WORD_RE = re.compile(
    r"[a-z][a-z0-9]{3,}"
)  # tokens >=4 chars (avoid spurious short-substring hits)


def _match_pack(
    kb_claims: dict[str, Claim],
    statement_quotes: tuple[str, ...],
    pack_field_keys: dict[str, tuple[str, ...]],
) -> str | None:
    """Pick the vertical pack whose namespace tokens appear (as whole words) in the client's prose
    or in what the client said in the interview, or ``None`` when nothing matches (a thin or
    non-vertical client gets no pack — honest)."""
    haystack: list[str] = [quote.lower() for quote in statement_quotes]
    for claim in kb_claims.values():
        if isinstance(claim.value_json, str):
            haystack.append(claim.value_json.lower())
        elif isinstance(claim.value_json, (dict, list)):
            haystack.append(json.dumps(claim.value_json).lower())
    words = set(_WORD_RE.findall(" ".join(haystack)))
    for pack_key in pack_field_keys:
        tokens = set(_WORD_RE.findall(pack_key.replace("_", " ")))
        if tokens & words:
            return pack_key
    return None


# --- LLM path (config-bounded; off-set names dropped) -----------------------


def _proposals_from_llm(
    gateway: LLMGateway,
    model: str,
    kb_claims: dict[str, Claim],
    project_statements: tuple[ProjectStatement, ...],
    *,
    scoring_keys: frozenset[str],
    deep_keys: frozenset[str],
    pack_field_keys: dict[str, tuple[str, ...]],
    pack_priors: dict[str, tuple[SourcePrior, ...]],
) -> tuple[
    list[ICPProposal],
    tuple[FieldProposalPayload, ...],
    tuple[_RejectedConcept, ...],
]:
    """Run the config-bounded synthesis LLM and map its JSON into proposals, dropping any field/pack
    it names outside the offered bounds. Any failure → ``[]`` (the caller falls back to floor)."""
    try:
        completion = gateway.complete(
            model=model,
            messages=_synthesis_messages(
                kb_claims, project_statements, scoring_keys, deep_keys, pack_field_keys
            ),
        )
    except Exception:  # noqa: BLE001 — any gateway failure degrades to the floor (never raises)
        return [], (), ()
    parsed = _parse_json(completion.text)
    if parsed is None:
        return [], (), ()
    raw_icps = parsed.get("icps")
    if not isinstance(raw_icps, list):
        return [], (), ()

    by_field, all_ids = _justifier(kb_claims)
    statement_ids = tuple(item.statement_id for item in project_statements)
    proposals: list[ICPProposal] = []
    seen_keys: set[str] = set()
    for index, raw in enumerate(raw_icps):
        if not isinstance(raw, dict):
            continue
        proposal = _proposal_from_raw(
            raw,
            index=index,
            seen_keys=seen_keys,
            by_field=by_field,
            all_ids=all_ids,
            statement_ids=statement_ids,
            scoring_keys=scoring_keys,
            deep_keys=deep_keys,
            pack_field_keys=pack_field_keys,
            pack_priors=pack_priors,
        )
        if proposal is not None:
            proposals.append(proposal)
    field_payloads, rejected = _field_proposal_payloads(raw_icps, scoring_keys, deep_keys, all_ids)
    return proposals, field_payloads, rejected


def _field_proposal_payloads(
    raw_icps: list[JsonValue],
    scoring_keys: frozenset[str],
    deep_keys: frozenset[str],
    evidence_ids: tuple[ClaimId, ...],
) -> tuple[tuple[FieldProposalPayload, ...], tuple[_RejectedConcept, ...]]:
    """Preserve well-formed, out-of-registry concepts without admitting them to the ICP."""
    known = scoring_keys | deep_keys
    drafts: dict[str, tuple[PassKind, dict[str, JsonValue] | None]] = {}
    rejected: list[_RejectedConcept] = []

    def notice(value: JsonValue, pass_kind: PassKind) -> None:
        if not isinstance(value, str) or value in known:
            return
        if is_valid_field_key(value):
            drafts.setdefault(value, (pass_kind, None))
        else:
            rejected.append(
                _RejectedConcept(
                    raw_input={"field_key": value, "pass_kind": pass_kind.value},
                    reason="field_key is malformed; expected a lowercase dotted identifier",
                )
            )

    for raw_icp in raw_icps:
        if not isinstance(raw_icp, dict):
            continue
        for value in _str_list(raw_icp.get("firmographic_field_keys")):
            notice(value, PassKind.SCORING)
        for value in _str_list(raw_icp.get("technographic_field_keys")):
            notice(value, PassKind.DEEP)
        raw_signals = raw_icp.get("candidate_signals")
        if isinstance(raw_signals, list):
            for signal in raw_signals:
                if not isinstance(signal, dict):
                    continue
                for value in _str_list(signal.get("proxy_field_keys")):
                    notice(value, PassKind.SCORING)
                for value in _str_list(signal.get("narrative_field_keys")):
                    notice(value, PassKind.DEEP)
        rubric = raw_icp.get("rubric")
        if isinstance(rubric, dict):
            for dimension in ("fit", "intent"):
                entries = rubric.get(dimension)
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if isinstance(entry, dict):
                        notice(entry.get("field_key"), PassKind.SCORING)

        concepts = raw_icp.get("new_field_concepts")
        if isinstance(concepts, list):
            for concept in concepts:
                if not isinstance(concept, dict):
                    rejected.append(
                        _RejectedConcept(
                            raw_input=concept,
                            reason="new field concept must be a JSON object",
                        )
                    )
                    continue
                key = concept.get("field_key")
                if not isinstance(key, str):
                    rejected.append(
                        _RejectedConcept(
                            raw_input=concept,
                            reason="new field concept requires a string field_key",
                        )
                    )
                    continue
                if key in known:
                    continue
                if not is_valid_field_key(key):
                    rejected.append(
                        _RejectedConcept(
                            raw_input=concept,
                            reason="field_key is malformed; expected a lowercase dotted identifier",
                        )
                    )
                    continue
                try:
                    pass_kind = PassKind(str(concept.get("pass_kind", PassKind.DEEP.value)))
                except ValueError:
                    rejected.append(
                        _RejectedConcept(
                            raw_input=concept,
                            reason="pass_kind must be scoring or deep",
                        )
                    )
                    continue
                drafts[key] = (pass_kind, concept)

    payloads: list[FieldProposalPayload] = []
    evidence_refs = tuple(str(claim_id) for claim_id in evidence_ids)
    for key, (pass_kind, concept) in drafts.items():
        raw = concept or {}
        reuse_raw = raw.get("reuse_scope")
        try:
            reuse_scope = ReuseScope(reuse_raw) if isinstance(reuse_raw, str) else None
            field_class = classify_field_key(key)
            pack = key.split(".", 1)[0] if field_class.value == "pack" else None
            value_schema = raw.get("value_schema")
            payloads.append(
                FieldProposalPayload(
                    field_def=FieldDef(
                        field_key=key,
                        value_type=(
                            str(raw.get("value_type"))
                            if isinstance(raw.get("value_type"), str)
                            else "str"
                        ),
                        tier_plan=("generic_web",),
                        pass_kind=pass_kind,
                        reuse_scope=reuse_scope,
                    ),
                    value_schema=value_schema if isinstance(value_schema, dict) else None,
                    description=(
                        str(raw.get("description"))
                        if isinstance(raw.get("description"), str)
                        else None
                    ),
                    pack=pack,
                    rationale=(
                        str(raw.get("rationale"))
                        if isinstance(raw.get("rationale"), str)
                        else "Out-of-registry concept noticed during ICP synthesis."
                    ),
                    evidence_refs=evidence_refs,
                )
            )
        except (ValidationError, ValueError) as exc:
            rejected.append(
                _RejectedConcept(
                    raw_input=raw,
                    reason=f"field concept failed proposal validation: {exc}",
                )
            )
    return tuple(payloads), tuple(rejected)


def _proposal_from_raw(
    raw: dict[str, JsonValue],
    *,
    index: int,
    seen_keys: set[str],
    by_field: dict[str, ClaimId],
    all_ids: tuple[ClaimId, ...],
    statement_ids: tuple[VolunteeredStatementId, ...],
    scoring_keys: frozenset[str],
    deep_keys: frozenset[str],
    pack_field_keys: dict[str, tuple[str, ...]],
    pack_priors: dict[str, tuple[SourcePrior, ...]],
) -> ICPProposal | None:
    """Map one raw LLM ICP dict into a bounded :class:`ICPProposal` (off-set field/pack names
    dropped). Returns ``None`` only if the result is wholly empty (nothing in bounds)."""
    icp_key = _slug(raw.get("icp_key"), index, seen_keys)

    firmo_keys = _bounded(_str_list(raw.get("firmographic_field_keys")), scoring_keys)
    firmo_raw = raw.get("firmographic")
    firmo_obj = firmo_raw if isinstance(firmo_raw, dict) else {}
    firmographic = FirmographicDimensions(
        industry=_opt_str(firmo_obj.get("industry")),
        size_band=_opt_str(firmo_obj.get("size_band")),
        geo=_opt_str(firmo_obj.get("geo")),
        revenue_band=_opt_str(firmo_obj.get("revenue_band")),
        field_keys=firmo_keys,
        justifying_claim_ids=_justify((CLIENT_ICP_EVIDENCE,), by_field, all_ids),
        justifying_statement_ids=statement_ids,
    )

    enabled_packs = tuple(pk for pk in _str_list(raw.get("enabled_packs")) if pk in pack_field_keys)
    allowed_pack_fields = {fk for pk in enabled_packs for fk in pack_field_keys.get(pk, ())}
    technographic = tuple(
        TechnographicDimension(
            field_key=fk,
            pack_key=_owning_pack(fk, enabled_packs, pack_field_keys),
            justifying_claim_ids=_justify(
                (CLIENT_PRODUCT, CLIENT_VALUE_PROP, CLIENT_DIFFERENTIATOR), by_field, all_ids
            ),
            justifying_statement_ids=statement_ids,
        )
        for fk in _str_list(raw.get("technographic_field_keys"))
        if fk in allowed_pack_fields
    )

    signals: list[CandidateSignal] = []
    raw_signals = raw.get("candidate_signals")
    if isinstance(raw_signals, list):
        for raw_signal in raw_signals:
            if not isinstance(raw_signal, dict):
                continue
            proxy = _bounded(_str_list(raw_signal.get("proxy_field_keys")), scoring_keys)
            narrative = _bounded(_str_list(raw_signal.get("narrative_field_keys")), deep_keys)
            if not (proxy or narrative):
                continue
            signals.append(
                CandidateSignal(
                    signal_class=_opt_str(raw_signal.get("signal_class")) or "signal",
                    proxy_field_keys=proxy,
                    narrative_field_keys=narrative,
                    justifying_claim_ids=_justify(
                        (CLIENT_DELIVERED_VALUE, CLIENT_ICP_EVIDENCE), by_field, all_ids
                    ),
                    justifying_statement_ids=statement_ids,
                )
            )

    rubric = _rubric_from_raw(raw.get("rubric"), scoring_keys, all_ids, statement_ids)

    source_profile = StartingSourceProfile(
        packs=enabled_packs,
        priors=tuple(p for pk in enabled_packs for p in pack_priors.get(pk, ())),
        justifying_claim_ids=all_ids,
        justifying_statement_ids=statement_ids,
    )

    if not (firmo_keys or technographic or signals or rubric.weights or enabled_packs):
        return None  # the model named nothing in-bounds — let the floor stand instead

    return ICPProposal(
        icp_key=icp_key,
        label=_opt_str(raw.get("label")),
        rationale=_opt_str(raw.get("rationale")),
        firmographic=firmographic,
        technographic=technographic,
        candidate_signals=tuple(signals),
        seed_accounts=(),  # seeds are M5.4's (resolved entities only); never minted from LLM text
        source_profile=source_profile,
        rubric=rubric,
        justifying_claim_ids=all_ids,
        justifying_statement_ids=statement_ids,
    )


def _rubric_from_raw(
    raw: JsonValue,
    scoring_keys: frozenset[str],
    all_ids: tuple[ClaimId, ...],
    statement_ids: tuple[VolunteeredStatementId, ...],
) -> ProposedRubric:
    """Map the raw rubric (``{fit:[{field_key,weight}], intent:[...], fit_threshold, ...}``) into a
    :class:`ProposedRubric`, keeping only fit/intent entries over **scoring** fields (the rest is
    rejected at confirm anyway — fail early)."""
    obj = raw if isinstance(raw, dict) else {}
    weights: list[RubricWeight] = []
    for dimension in ("fit", "intent"):
        entries = obj.get(dimension)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            field_key = entry.get("field_key")
            if not isinstance(field_key, str) or field_key not in scoring_keys:
                continue
            weights.append(
                RubricWeight(
                    field_key=field_key,
                    dimension=dimension,
                    weight=_opt_float(entry.get("weight"), default=1.0),
                    justifying_claim_ids=all_ids,
                    justifying_statement_ids=statement_ids,
                )
            )
    return ProposedRubric(
        weights=tuple(weights),
        fit_threshold=_opt_float(obj.get("fit_threshold"), default=0.5, unit=True),
        intent_threshold=_opt_float(obj.get("intent_threshold"), default=0.3, unit=True),
    )


def _synthesis_messages(
    kb_claims: dict[str, Claim],
    project_statements: tuple[ProjectStatement, ...],
    scoring_keys: frozenset[str],
    deep_keys: frozenset[str],
    pack_field_keys: dict[str, tuple[str, ...]],
) -> list[Message]:
    """The config-bounded synthesis prompt: the client facts + what the client said about targeting
    in the interview + the offered packs / candidate fields, with the hard rules. The model may only
    choose among the offered names; the runtime guard drops anything else regardless of what it
    returns."""
    facts = {fk: claim.value_json for fk, claim in kb_claims.items()}
    statements: list[JsonValue] = [
        {
            "statement_id": str(item.statement_id),
            "route_key": item.route_key,
            "quote": item.quote,
        }
        for item in project_statements
    ]
    system = (
        "You are an ICP (ideal customer profile) synthesizer for a B2B research pipeline. Given a "
        "client's knowledge base, the targeting statements the client made in the Stage-0 "
        "interview, and a fixed catalog of packs and candidate field keys, propose "
        "one or more candidate ICPs as structured hypotheses. The interview statements are the "
        "client's own words about who they want to target: treat them as evidence of equal "
        "standing to the knowledge base, and never contradict them. Propose MULTIPLE ICPs only "
        "when the client's customer evidence clearly clusters into distinct segments.\n"
        "HARD RULES:\n"
        "1. Existing ICP slots may use ONLY field_keys and pack keys from the provided catalog. "
        "If an important concept is missing, keep it OUT of those slots and describe it under "
        "new_field_concepts for governed review. Never invent a company or a fact.\n"
        "2. Fit and intent rubric entries must be SCORING field_keys (cheap Pass-A proxies).\n"
        "3. Do not propose seed accounts (those are resolved separately).\n"
        'Return STRICT JSON: {"icps": [{"icp_key": str, "label": str, "rationale": str, '
        '"firmographic": {"industry": str, "size_band": str, "geo": str, "revenue_band": str}, '
        '"firmographic_field_keys": [field_key, ...], "enabled_packs": [pack_key, ...], '
        '"technographic_field_keys": [field_key, ...], "candidate_signals": [{"signal_class": str, '
        '"proxy_field_keys": [scoring_field_key, ...], "narrative_field_keys": [deep_field_key, '
        '...]}], "rubric": {"fit": [{"field_key": scoring_field_key, "weight": number}], "intent": '
        '[{"field_key": scoring_field_key, "weight": number}], "fit_threshold": number, '
        '"intent_threshold": number}, "new_field_concepts": [{"field_key": str, '
        '"value_type": str, "pass_kind": "scoring"|"deep", "reuse_scope": '
        '"public_footprint"|"tenant_private"|null, "description": str, "rationale": str}]}]}. '
        "No prose, no code fences."
    )
    user = json.dumps(
        {
            "client_facts": facts,
            "project_statements": statements,
            "packs": {pk: list(fks) for pk, fks in pack_field_keys.items()},
            "scoring_field_keys": sorted(scoring_keys),
            "deep_field_keys": sorted(deep_keys),
        }
    )
    return [Message(role=Role.SYSTEM, content=system), Message(role=Role.USER, content=user)]


# --- small parse helpers ----------------------------------------------------


def _parse_json(text: str) -> dict[str, JsonValue] | None:
    """Parse the LLM's JSON object, tolerating fences/prose; ``None`` if unusable (→ floor)."""
    start, end = text.find("{"), text.rfind("}")
    for candidate in (text, text[start : end + 1] if 0 <= start < end else None):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _str_list(value: JsonValue) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(v for v in value if isinstance(v, str) and v)


def _bounded(keys: tuple[str, ...], allowed: frozenset[str]) -> tuple[str, ...]:
    """Keep only in-bounds keys, de-duplicated in first-seen order (the hard config guard)."""
    out: list[str] = []
    for key in keys:
        if key in allowed and key not in out:
            out.append(key)
    return tuple(out)


def _owning_pack(
    field_key: str, enabled_packs: tuple[str, ...], pack_field_keys: dict[str, tuple[str, ...]]
) -> str:
    return next((pk for pk in enabled_packs if field_key in pack_field_keys.get(pk, ())), "")


def _opt_str(value: JsonValue) -> str | None:
    return value if isinstance(value, str) and value else None


def _opt_float(value: JsonValue, *, default: float, unit: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    result = float(value)
    if unit:
        return 0.0 if result < 0.0 else 1.0 if result > 1.0 else result
    return result if result >= 0.0 else default


def _slug(value: JsonValue, index: int, seen: set[str]) -> str:
    """A unique, well-formed ``icp_key`` for the proposal (falls back to ``icp_<n>``)."""
    base = value.strip().lower() if isinstance(value, str) and value.strip() else f"icp_{index + 1}"
    base = re.sub(r"[^a-z0-9_]+", "_", base).strip("_") or f"icp_{index + 1}"
    key, suffix = base, 2
    while key in seen:
        key = f"{base}_{suffix}"
        suffix += 1
    seen.add(key)
    return key
