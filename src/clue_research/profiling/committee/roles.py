"""Role inference + the role-plausibility gate (M8.3).

For each admitted committee member, infer the buying-committee role (champion / economic_buyer /
technical_evaluator / blocker) from the person's title + org context, then run a **plausibility
gate** that *rejects* an implausible assignment rather than guessing (staged-flow §8 — the
prototype's "wrong people / wrong roles" failure made structural).

Two anti-hallucination disciplines live here:

* **All LLM inference goes through the shared OpenRouter ``LLMGateway``** (``core.gateway``) — model
  id as config, never a provider SDK (the gateway-vs-resolver split, M8 spec). The response
  is parsed with a robust extractor and **fails safe** — an unparseable / errored call falls back to
  a deterministic title heuristic at low confidence, never raising.
* **The plausibility gate** keys on title seniority: ``economic_buyer`` requires budget authority
  (executive/senior), so a clearly junior title proposed as ``economic_buyer`` is *flagged, not
  promoted* — its role claim is written with ``plausible=false`` and a confidence clamped below the
  promotion floor (M8.3 AC; M9 makes the promotion decision, M8.3 only tags).
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from clue_research.core import (
    AccountEntity,
    Completion,
    Confidence,
    CostCents,
    LLMGateway,
    Message,
    Persona,
    Role,
)

_PERSONA_VALUES: frozenset[str] = frozenset(p.value for p in Persona)


class RoleSeniority(StrEnum):
    """Coarse title seniority — the plausibility gate's input."""

    EXECUTIVE = "executive"
    SENIOR = "senior"
    MID = "mid"
    JUNIOR = "junior"
    UNKNOWN = "unknown"


# Keyword sets, checked in priority order (executive → senior → junior → mid). Lowercased
# substring match against the title; the first matching band wins, so "senior engineer" is SENIOR
# (senior beats engineer) and "VP of Engineering" is EXECUTIVE (vp beats engineering).
_EXECUTIVE_KW = (
    "chief",
    "ceo",
    "cfo",
    "coo",
    "cto",
    "cmo",
    "ciso",
    "cio",
    "founder",
    "co-founder",
    "owner",
    "president",
    "vp",
    "vice president",
    "svp",
    "evp",
    "partner",
    "managing director",
    "head of",
)
_SENIOR_KW = ("director", "principal", "staff", "senior", "lead", "head")
_JUNIOR_KW = (
    "intern",
    "junior",
    "jr",
    "trainee",
    "entry",
    "apprentice",
    "student",
    "fellow",
    "associate",
    "assistant",
    "coordinator",
)
_MID_KW = (
    "manager",
    "engineer",
    "developer",
    "analyst",
    "consultant",
    "designer",
    "scientist",
    "specialist",
    "administrator",
    "architect",
)

# Technical-title markers — the fail-safe heuristic routes these to technical_evaluator.
_TECHNICAL_KW = (
    "engineer",
    "developer",
    "architect",
    "data",
    "ml",
    "machine learning",
    "devops",
    "security",
    "infrastructure",
    "platform",
    "scientist",
    "technical",
    "cto",
    "it",
)
# Procurement / legal / security-officer markers — the fail-safe heuristic routes these to blocker.
_BLOCKER_KW = (
    "procurement",
    "legal",
    "counsel",
    "compliance",
    "purchasing",
    "ciso",
    "security officer",
)


class RoleInference(BaseModel):
    """The raw role-inference result (pre-gate). ``role`` is ``None`` when the model output could
    not be parsed into a valid persona (the gate then falls back to the title heuristic)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Persona | None
    confidence: Confidence = 0.0
    rationale: str = ""
    cost_cents: CostCents = Decimal(0)


class RoleVerdict(BaseModel):
    """The gated role assignment written to ``contact.role_on_committee``. ``plausible=False`` +
    a clamped ``confidence`` is the "flagged, not promoted" signal for an implausible assignment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Persona
    confidence: Confidence
    plausible: bool
    rationale: str = ""
    cost_cents: CostCents = Decimal(0)


def _clamp01(value: object) -> float:
    """Coerce a value to a [0, 1] float, defaulting to 0.0 on anything non-numeric."""
    try:
        return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    """Whether any keyword appears in ``text`` as a whole word/phrase (word-boundary match).

    Substring matching is unsafe for abbreviation keywords — "dire**cto**r" contains "cto", "it"
    hides in "aud**it**" — so every keyword is matched on word boundaries, which also handles
    multi-word phrases ("head of", "vice president")."""
    return any(re.search(rf"\b{re.escape(kw)}\b", text) for kw in keywords)


def title_seniority(title: str | None) -> RoleSeniority:
    """Classify a job title into a coarse seniority band (the plausibility gate's input)."""
    if not title or not title.strip():
        return RoleSeniority.UNKNOWN
    t = title.lower()
    if _has_keyword(t, _EXECUTIVE_KW):
        return RoleSeniority.EXECUTIVE
    if _has_keyword(t, _SENIOR_KW):
        return RoleSeniority.SENIOR
    if _has_keyword(t, _JUNIOR_KW):
        return RoleSeniority.JUNIOR
    if _has_keyword(t, _MID_KW):
        return RoleSeniority.MID
    return RoleSeniority.UNKNOWN


def role_plausible(seniority: RoleSeniority, role: Persona) -> bool:
    """Whether ``role`` is plausible for a person of ``seniority``.

    The one structural check (staged-flow §8): ``economic_buyer`` implies budget authority, so it is
    plausible only for an executive/senior title — a junior/mid/unknown title proposed as the
    economic buyer is implausible (the canonical "intern as economic_buyer" failure). The other
    three roles can plausibly attach to any seniority (anyone can champion, evaluate, or block)."""
    if role is Persona.ECONOMIC_BUYER:
        return seniority in (RoleSeniority.EXECUTIVE, RoleSeniority.SENIOR)
    return True


def _heuristic_role(title: str | None) -> Persona:
    """A deterministic title-based role fallback when the LLM output is unusable.

    Grounded in the title, never arbitrary: budget titles → economic_buyer, technical titles →
    technical_evaluator, procurement/legal → blocker, else champion (the safest default — a
    mis-assigned champion carries no authority implication, unlike economic_buyer)."""
    seniority = title_seniority(title)
    t = (title or "").lower()
    if _has_keyword(t, _BLOCKER_KW):
        return Persona.BLOCKER
    if _has_keyword(t, _TECHNICAL_KW):
        return Persona.TECHNICAL_EVALUATOR
    if seniority is RoleSeniority.EXECUTIVE:
        return Persona.ECONOMIC_BUYER
    return Persona.CHAMPION


def _first_json_object(text: str) -> dict[str, object] | None:
    """Extract and parse the first balanced ``{...}`` JSON object in ``text`` (robust to code
    fences / prose around it). Returns ``None`` if none parses — the caller then fails safe.

    M8 ships its own extractor rather than importing M9's faithfulness parser (worker
    independence: ``profiling`` may not import ``verification``)."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        parsed = json.loads(candidate)
                    except json.JSONDecodeError:
                        break  # malformed — advance to the next "{"
                    return parsed if isinstance(parsed, dict) else None
        start = text.find("{", start + 1)
    return None


_ROLE_SYSTEM_PROMPT = (
    "You classify a person's role on a B2B buying committee. Choose exactly one role from this "
    "closed set: champion, economic_buyer, technical_evaluator, blocker. "
    "champion = an internal advocate; economic_buyer = holds budget authority (an executive/senior "
    "decision-maker); technical_evaluator = assesses the technical fit; blocker = can veto "
    "(procurement, legal, security). Base the role ONLY on the title and company context "
    "provided — do not invent facts about the person. Reply with a single JSON object only: "
    '{"role": <one of the four>, "confidence": <0.0-1.0>, "rationale": <short string>}.'
)


def build_role_messages(
    candidate_title: str | None,
    account: AccountEntity,
    *,
    relevant_personas: tuple[Persona, ...] = (),
) -> list[Message]:
    """Build the role-inference prompt from the title + account context (+ the ICP-relevant
    personas, D5 multi-ICP). The title/context are the only inputs — the model classifies, it never
    introduces a person (target-lock discipline)."""
    persona_note = (
        f" The ICP cares most about these personas: "
        f"{', '.join(p.value for p in relevant_personas)}."
        if relevant_personas
        else ""
    )
    user = (
        f"Company: {account.canonical_name}"
        + (f" ({account.primary_domain})" if account.primary_domain else "")
        + f".\nPerson title: {candidate_title or 'unknown'}.{persona_note}\n"
        "Classify this person's buying-committee role."
    )
    return [
        Message(role=Role.SYSTEM, content=_ROLE_SYSTEM_PROMPT),
        Message(role=Role.USER, content=user),
    ]


def infer_role(
    gateway: LLMGateway,
    model: str,
    candidate_title: str | None,
    account: AccountEntity,
    *,
    relevant_personas: tuple[Persona, ...] = (),
) -> RoleInference:
    """Infer a role via the gateway; parse robustly and **fail safe** (never raise).

    A failed call or unparseable/invalid output yields ``role=None`` (the gate falls back to the
    title heuristic). Captures the call cost so the worker can account for committee spend."""
    messages = build_role_messages(candidate_title, account, relevant_personas=relevant_personas)
    try:
        completion: Completion = gateway.complete(model=model, messages=messages)
    except Exception:  # noqa: BLE001 — a model error must never abort discovery; fail safe
        return RoleInference(role=None, confidence=0.0, rationale="role inference call failed")

    obj = _first_json_object(completion.text)
    if obj is None:
        return RoleInference(
            role=None,
            confidence=0.0,
            rationale="unparseable role response",
            cost_cents=completion.cost_cents,
        )
    raw_role = str(obj.get("role", "")).strip().lower()
    role = Persona(raw_role) if raw_role in _PERSONA_VALUES else None
    return RoleInference(
        role=role,
        confidence=_clamp01(obj.get("confidence")),
        rationale=str(obj.get("rationale", ""))[:500],
        cost_cents=completion.cost_cents,
    )


def gate_role(
    inference: RoleInference,
    candidate_title: str | None,
    *,
    implausible_confidence_ceiling: float,
    fallback_confidence: float,
) -> RoleVerdict:
    """Apply the plausibility gate to an inference, producing the role written to the store.

    On a parse failure (``inference.role is None``) the role falls back to the deterministic title
    heuristic at ``fallback_confidence``. On an *implausible* assignment (e.g. a junior title as
    economic_buyer) the role is kept but **flagged**: ``plausible=False`` and the confidence is
    clamped to ``implausible_confidence_ceiling`` (below the promotion floor) — so M9 will not
    promote it (M8.3 AC: "not admitted as economic_buyer, or is flagged not promoted")."""
    if inference.role is not None:
        role = inference.role
        confidence: float = inference.confidence
    else:
        role = _heuristic_role(candidate_title)
        confidence = min(inference.confidence, fallback_confidence)

    plausible = role_plausible(title_seniority(candidate_title), role)
    if not plausible:
        confidence = min(confidence, implausible_confidence_ceiling)

    return RoleVerdict(
        role=role,
        confidence=confidence,
        plausible=plausible,
        rationale=inference.rationale,
        cost_cents=inference.cost_cents,
    )
