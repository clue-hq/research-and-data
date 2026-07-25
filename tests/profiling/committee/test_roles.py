"""M8.3 role inference + role-plausibility gate (pure — no DB).

Covers the gateway-driven role inference (robust JSON parse + fail-safe), the title-seniority
classifier, and the plausibility gate that flags an implausible assignment (the AC's
intern-as-economic_buyer case) rather than guessing.
"""

from __future__ import annotations

from clue_core import AccountEntity, Persona, new_entity_id
from clue_research.profiling.committee.roles import (
    RoleSeniority,
    _first_json_object,
    gate_role,
    infer_role,
    role_plausible,
    title_seniority,
)

from ..conftest import FakeGateway


def _account() -> AccountEntity:
    return AccountEntity(
        id=new_entity_id(),
        canonical_name="Acme Robotics",
        primary_domain="acme.example",
        workspace_id="ws-test",
    )


# --- title seniority --------------------------------------------------------
def test_title_seniority_bands() -> None:
    assert title_seniority("Chief Financial Officer") is RoleSeniority.EXECUTIVE
    assert title_seniority("VP of Engineering") is RoleSeniority.EXECUTIVE
    assert title_seniority("Senior Software Engineer") is RoleSeniority.SENIOR
    assert title_seniority("Director of Procurement") is RoleSeniority.SENIOR
    assert title_seniority("Software Engineer") is RoleSeniority.MID
    assert title_seniority("Engineering Intern") is RoleSeniority.JUNIOR
    assert title_seniority("Junior Analyst") is RoleSeniority.JUNIOR
    assert title_seniority(None) is RoleSeniority.UNKNOWN
    assert title_seniority("") is RoleSeniority.UNKNOWN


# --- plausibility -----------------------------------------------------------
def test_economic_buyer_requires_authority() -> None:
    assert role_plausible(RoleSeniority.EXECUTIVE, Persona.ECONOMIC_BUYER)
    assert role_plausible(RoleSeniority.SENIOR, Persona.ECONOMIC_BUYER)
    assert not role_plausible(RoleSeniority.MID, Persona.ECONOMIC_BUYER)
    assert not role_plausible(RoleSeniority.JUNIOR, Persona.ECONOMIC_BUYER)
    assert not role_plausible(RoleSeniority.UNKNOWN, Persona.ECONOMIC_BUYER)


def test_other_roles_plausible_for_any_seniority() -> None:
    for role in (Persona.CHAMPION, Persona.TECHNICAL_EVALUATOR, Persona.BLOCKER):
        for seniority in RoleSeniority:
            assert role_plausible(seniority, role)


# --- robust JSON extraction -------------------------------------------------
def test_first_json_object_handles_fences_and_prose() -> None:
    text = 'Sure!\n```json\n{"role": "champion", "confidence": 0.7}\n```\nThanks'
    obj = _first_json_object(text)
    assert obj == {"role": "champion", "confidence": 0.7}


def test_first_json_object_returns_none_on_garbage() -> None:
    assert _first_json_object("no json here") is None
    assert _first_json_object("{ not valid json") is None


# --- inference (gateway) ----------------------------------------------------
def test_infer_role_parses_valid_response() -> None:
    gateway = FakeGateway(
        reply='{"role": "technical_evaluator", "confidence": 0.8, "rationale": "VP Eng"}'
    )
    inference = infer_role(gateway, "model-x", "VP of Engineering", _account())
    assert inference.role is Persona.TECHNICAL_EVALUATOR
    assert inference.confidence == 0.8
    assert gateway.complete_calls == 1


def test_infer_role_fails_safe_on_unparseable() -> None:
    # The real StubGateway returns "stub:<hash>" (non-JSON) — fail safe to role=None, never raise.
    gateway = FakeGateway(reply="stub:deadbeef not json")
    inference = infer_role(gateway, "model-x", "CFO", _account())
    assert inference.role is None
    assert inference.confidence == 0.0


def test_infer_role_rejects_invalid_role_value() -> None:
    gateway = FakeGateway(reply='{"role": "ceo", "confidence": 0.9}')  # not a committee persona
    inference = infer_role(gateway, "model-x", "CEO", _account())
    assert inference.role is None  # "ceo" is not in the closed persona set


# --- the gate (the make-or-break: flag, don't guess) ------------------------
def test_gate_flags_implausible_junior_economic_buyer() -> None:
    """A clearly junior title inferred as economic_buyer is flagged-not-promoted: plausible=False
    and confidence clamped below the promotion floor (M8.3 AC)."""
    gateway = FakeGateway(reply='{"role": "economic_buyer", "confidence": 0.95}')
    inference = infer_role(gateway, "model-x", "Engineering Intern", _account())
    verdict = gate_role(
        inference,
        "Engineering Intern",
        implausible_confidence_ceiling=0.15,
        fallback_confidence=0.2,
    )
    assert verdict.role is Persona.ECONOMIC_BUYER  # the inferred role is recorded...
    assert verdict.plausible is False  # ...but flagged
    assert verdict.confidence <= 0.15  # ...and not promotable (below the floor)


def test_gate_keeps_plausible_executive_economic_buyer() -> None:
    gateway = FakeGateway(reply='{"role": "economic_buyer", "confidence": 0.9}')
    inference = infer_role(gateway, "model-x", "Chief Financial Officer", _account())
    verdict = gate_role(
        inference,
        "Chief Financial Officer",
        implausible_confidence_ceiling=0.15,
        fallback_confidence=0.2,
    )
    assert verdict.role is Persona.ECONOMIC_BUYER
    assert verdict.plausible is True
    assert verdict.confidence == 0.9  # unclamped


def test_gate_falls_back_to_title_heuristic_on_parse_failure() -> None:
    gateway = FakeGateway(reply="not json at all")
    inference = infer_role(gateway, "model-x", "Staff Software Engineer", _account())
    assert inference.role is None
    verdict = gate_role(
        inference,
        "Staff Software Engineer",
        implausible_confidence_ceiling=0.15,
        fallback_confidence=0.2,
    )
    # A technical title → technical_evaluator (plausible), at the fallback confidence.
    assert verdict.role is Persona.TECHNICAL_EVALUATOR
    assert verdict.plausible is True
    assert verdict.confidence <= 0.2
