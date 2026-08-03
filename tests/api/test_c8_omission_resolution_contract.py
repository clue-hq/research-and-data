"""PC-C8 AC-7, last clause: a card may not emit an omission its surface cannot resolve.

The card deliberately names no tool (spec §3/§7) — it emits a typed *kind* and an opaque cursor,
and the resource manifest decides which tool is installed to accept that cursor. That indirection
is what stops a card advertising a capability the profile lacks, but it also means the two halves
can drift apart silently: the compiler can start emitting a kind, or a profile can stop installing
a tool, and the only symptom is a model handed a resume cursor with nothing to hand it to.

This is the join, asserted rather than assumed, and deliberately **count-agnostic**: it walks every
member of :class:`Stage0CardOmissionKind`, so a new kind added without a resolution decision fails
here on the day it is added rather than the day a card first emits it.
"""

from __future__ import annotations

import pytest

from clue_agents import AgentRole
from clue_agents.registry import AgentProfileRegistry
from clue_api.agent_registry_wiring import (
    STAGE0_CONVERSATION_TRIAL_SURFACE,
    build_agent_profile_registry,
)
from clue_api.recipe_wiring import load_system_recipe_definitions
from clue_api.stage0_inspection_tools import (
    READINESS_CURSOR_KIND,
    STATEMENT_CURSOR_KINDS,
)
from clue_api.stage0_trial import STAGE0_RECIPE_VERSION
from clue_api.toolbelt_wiring import build_toolbelt
from clue_execution import GateNode
from clue_projections import Stage0CardOmissionKind
from tests.api.conftest import hermetic_flag_env

#: The card's cursor kind for each omission kind that carries one — mirrored from the compiler's
#: own ``encode_card_cursor({"kind": …})`` calls (``clue_projections.stage0._omissions``).
_CURSOR_KIND: dict[Stage0CardOmissionKind, str] = {
    Stage0CardOmissionKind.STATEMENTS_OVER_CAP: "statements",
    Stage0CardOmissionKind.EXCLUDED_STATEMENT_EVIDENCE_MISSING: "excluded_statement_evidence",
    Stage0CardOmissionKind.READINESS_HISTORY: "readiness_history",
    Stage0CardOmissionKind.CLIENT_KNOWLEDGE_OVER_CAP: "client_knowledge",
}

#: Cursor kind → the tool whose contract accepts it, read off the tools themselves rather than
#: restated here, so a tool that narrows what it accepts fails this test instead of drifting.
_ACCEPTED_BY: dict[str, str] = {
    **dict.fromkeys(STATEMENT_CURSOR_KINDS, "inspect_statement_history"),
    READINESS_CURSOR_KIND: "inspect_readiness_history",
}

#: Kinds with no resolving tool, each with the reason it is allowed to have none. An entry here is
#: a *decision*, not an oversight — which is the whole point of making the walk exhaustive.
_UNRESOLVABLE_BY_DESIGN: dict[Stage0CardOmissionKind, str] = {
    # Spec §7 defers `inspect_client_claim` deliberately: an exact-claim/provenance read is
    # platform-general, not a Stage-0 surface, and deciding it here would invite a fourth
    # near-identical claim reader. Ledgered with the C6 toolbelt owner.
    Stage0CardOmissionKind.CLIENT_KNOWLEDGE_OVER_CAP: "spec §7 deferred inspect_client_claim",
    # Self-describing: it says "there were more omissions than the cap", which is complete on its
    # own. `test_the_self_describing_omission_kind_carries_no_cursor` holds it to that.
    Stage0CardOmissionKind.OMISSIONS_TRUNCATED: "carries a count only, never a cursor",
}

#: Every surface that is handed a Stage-0 project card. The trial is not an exception here: §7
#: sanctions the inspection tools on it, and a restricted surface is exactly where an unresolvable
#: omission would first appear.
_CARD_SURFACES: tuple[tuple[AgentRole, str | None], ...] = (
    (AgentRole.HEAD_OF_ABM, None),
    (AgentRole.HEAD_OF_ABM, STAGE0_CONVERSATION_TRIAL_SURFACE),
)


@pytest.fixture(scope="module")
def registry() -> AgentProfileRegistry:
    with hermetic_flag_env():
        return build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))


def test_every_omission_kind_is_either_resolvable_or_a_recorded_decision() -> None:
    """The exhaustiveness half: no kind may be un-triaged."""

    for kind in Stage0CardOmissionKind:
        resolvable = kind in _CURSOR_KIND and _CURSOR_KIND[kind] in _ACCEPTED_BY
        deferred = kind in _UNRESOLVABLE_BY_DESIGN
        assert resolvable != deferred, (
            f"omission kind {kind.value!r} is neither resolved by an inspection tool nor recorded "
            "as a deliberate exception — decide which, in this file"
        )


@pytest.mark.parametrize(("role", "surface"), _CARD_SURFACES)
def test_a_card_surface_installs_the_tool_for_every_omission_it_can_emit(
    registry: AgentProfileRegistry,
    role: AgentRole,
    surface: str | None,
) -> None:
    """AC-7's last clause: a profile that cannot resolve an emittable omission is a failing build.

    This is the assertion the trial surface makes non-trivial. Withholding tools is how PC-C8 §8
    enforces its restrictions, so the *same* mechanism that removes `start_recon` could remove an
    inspection tool — and the card would go on emitting cursors into a surface with nothing to
    accept them.
    """

    resolved = registry.resolve(role, surface=surface)
    installed = {pin.name for pin in resolved.profile.tools}

    unresolvable = sorted(
        f"{kind.value} -> {_ACCEPTED_BY[_CURSOR_KIND[kind]]}"
        for kind in Stage0CardOmissionKind
        if kind not in _UNRESOLVABLE_BY_DESIGN and _ACCEPTED_BY[_CURSOR_KIND[kind]] not in installed
    )
    assert unresolvable == []
    # The manifest is what the constitution pins, so it must agree with the effective tool set —
    # a manifest that omitted the tool would advertise a narrower surface than the model gets.
    assert installed == {pin.name for pin in resolved.resource_manifest.tools}


#: The Stage-0 interaction slot: the C5 gate node every agent-planned tool call is appended
#: beneath, and whose ``dynamic_tool_allowlist`` is the second, independent ceiling on what the
#: trial can actually run.
_STAGE0_SLOT_KEY = "stage0_interactions"


def test_the_pinned_recipe_revision_allows_every_omission_resolving_tool(
    registry: AgentProfileRegistry,
) -> None:
    """The other half of "installed": a profile grant the pinned C5 slot does not allow is inert.

    Granting the tool on the profile is necessary but not sufficient. A plan step is validated
    twice — against the resolved profile *and* against the promoted recipe revision's interaction
    slot (``agent_execution_wiring`` → ``c5_tool_not_allowed``) — so a card can advertise an
    omission cursor, the profile can install the tool that resolves it, and the call can still be
    rejected because the pinned revision's ``tool_allowlist`` predates the grant. That is exactly
    what happened between profile v10 and ``recipe0-stage0@4``: the live trial refused
    ``inspect_readiness_history@1`` while every profile-level assertion above passed.
    """

    definition = next(
        item
        for item in load_system_recipe_definitions()
        if item.recipe_key == "recipe0-stage0" and item.version == STAGE0_RECIPE_VERSION
    )
    slot = next(node for node in definition.graph.nodes if node.node_key == _STAGE0_SLOT_KEY)
    assert isinstance(slot, GateNode)

    # Exact addresses, read off the surface's own pins rather than restated: the slot allowlist is
    # keyed on `name@version`, so a version bump on either side has to meet in the middle here.
    resolved = registry.resolve(AgentRole.HEAD_OF_ABM, surface=STAGE0_CONVERSATION_TRIAL_SURFACE)
    installed = {pin.name: pin.address for pin in resolved.profile.tools}
    required = sorted(
        installed[_ACCEPTED_BY[_CURSOR_KIND[kind]]]
        for kind in Stage0CardOmissionKind
        if kind not in _UNRESOLVABLE_BY_DESIGN
    )
    missing = [address for address in required if address not in slot.dynamic_tool_allowlist]
    assert missing == []
    # The graph-wide allowlist is the outer ceiling the slot's own list must sit inside; a slot
    # entry absent from it fails promotion rather than the turn, but state it here too so the
    # revision this test reads is the one that could actually promote.
    assert [item for item in required if item not in definition.graph.tool_allowlist] == []


def test_the_self_describing_omission_kind_carries_no_cursor() -> None:
    """`omissions_truncated` is exempt only because it never asks anyone to resume it."""

    assert Stage0CardOmissionKind.OMISSIONS_TRUNCATED not in _CURSOR_KIND


def test_the_deferred_kind_is_named_with_its_reason() -> None:
    """A deferral without a reason is indistinguishable from a forgotten kind."""

    for kind, reason in _UNRESOLVABLE_BY_DESIGN.items():
        assert reason.strip(), kind.value
        assert kind in Stage0CardOmissionKind
