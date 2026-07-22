"""The concrete toolbelt — the out-of-order matrix (the step-2 de-risk).

On a fresh workspace with **no** prerequisites, every registered tool either raises
``PreconditionFailed`` with its documented ``reason_code`` or — for the genuinely prerequisite-free
tools (``reverse_profile`` / ``estimate_project`` / ``start_project_run``) — succeeds with a real
result. Never a silent-empty success (pre-mortem #2). The matrix asserts the **full** registered
tool list is covered, so a new tool without a matrix entry fails the test.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from clue_api.toolbelt_wiring import build_toolbelt
from clue_core import ProjectRunId, new_project_run_id
from clue_research.stage0 import ICPProposal
from clue_toolbelt import PreconditionFailed, ToolContext, ToolResult, invoke_tool
from tests.api.conftest import require_profiling_db as require_profiling_db  # noqa: F401
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn, seed_packs

TTL = 86400.0
_UUID = lambda: str(uuid4())  # noqa: E731


class _FakeRunMachine:
    """A stand-in ``ProjectRun`` for the matrix: only ``start`` is reached (it has no precondition);
    every other run-control tool is blocked by ``run_not_found`` before its invoke runs. Keeps the
    matrix isolated (no committed run rows outside the test's rolled-back transaction)."""

    async def start(self, **kwargs: object) -> ProjectRunId:
        return new_project_run_id()


# tool -> ("precondition", reason_code) | ("success", a required reference key)
_MATRIX: dict[str, tuple[str, str]] = {
    "reverse_profile": ("success", "client_entity_id"),
    "synthesize_icps": ("precondition", "no_client_kb"),
    "confirm_icp": ("precondition", "no_client_kb"),
    "import_accounts": ("precondition", "no_active_icp"),
    "discover_accounts": ("precondition", "run_not_found"),
    "score_accounts": ("precondition", "run_not_found"),
    "submit_tier_checkpoint": ("precondition", "run_not_found"),
    "run_deep_account": ("precondition", "no_active_icp"),
    "resolve_committee": ("precondition", "account_not_found"),
    "profile_contact": ("precondition", "account_not_found"),
    "run_verification": ("precondition", "run_not_found"),
    "compose_handoff": ("precondition", "run_not_found"),
    "estimate_project": ("success", "estimated_cost_cents"),
    "start_project_run": ("success", "project_run_id"),
    "pause_run": ("precondition", "run_not_found"),
    "resume_run": ("precondition", "run_not_found"),
    "adjust_budget": ("precondition", "run_not_found"),
}


def _bodies() -> dict[str, dict[str, object]]:
    return {
        "reverse_profile": {"name": "Acme Robotics", "website": "https://acme.example"},
        "synthesize_icps": {"client_entity_id": _UUID()},
        "confirm_icp": {
            "client_entity_id": _UUID(),
            "proposal": ICPProposal(icp_key="matrix").model_dump(mode="json"),
        },
        "import_accounts": {"client_entity_id": _UUID(), "icp_key": "matrix", "rows": []},
        "discover_accounts": {"project_run_id": _UUID()},
        "score_accounts": {"project_run_id": _UUID()},
        "submit_tier_checkpoint": {"project_run_id": _UUID()},
        "run_deep_account": {"account_entity_id": _UUID(), "icp_key": "matrix", "tier": "top"},
        "resolve_committee": {"account_entity_id": _UUID()},
        "profile_contact": {
            "contact_entity_id": _UUID(),
            "account_entity_id": _UUID(),
            "tier": "top",
        },
        "run_verification": {"project_run_id": _UUID()},
        "compose_handoff": {"project_run_id": _UUID()},
        "estimate_project": {},
        "start_project_run": {"icp_key": "matrix", "icp_version": 1},
        "pause_run": {"project_run_id": _UUID()},
        "resume_run": {"project_run_id": _UUID()},
        "adjust_budget": {"project_run_id": _UUID(), "budget_cap_cents": 1000},
    }


def test_out_of_order_matrix(require_profiling_db: None) -> None:  # noqa: F811
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            await seed_packs(conn)  # core + deep + committee; stage-0 packs load below
            from clue_api.composition import load_research_packs

            await load_research_packs(conn)  # client-KB / ICP / import packs (idempotent)
            cf = conn_session_factory(conn)
            registry = build_toolbelt(
                gateway=None,  # spend tools are blocked by preconditions; invoke never reached
                run_machine=_FakeRunMachine(),  # type: ignore[arg-type]
                conn_factory=cf,
            )
            ctx = ToolContext(workspace_id=f"ws_{uuid4().hex[:8]}", actor="human", conn_factory=cf)
            bodies = _bodies()

            # Coverage: every registered tool has a matrix entry (a new tool without one fails).
            assert set(registry.names()) == set(_MATRIX), (
                f"matrix/registry drift: {set(registry.names()) ^ set(_MATRIX)}"
            )

            for name in registry.names():
                kind, expected = _MATRIX[name]
                if kind == "success":
                    result = await invoke_tool(
                        registry, name, bodies[name], ctx, idempotency_ttl_s=TTL
                    )
                    assert isinstance(result, ToolResult)
                    assert expected in result.references, f"{name}: missing ref {expected!r}"
                else:
                    with pytest.raises(PreconditionFailed) as ei:
                        await invoke_tool(registry, name, bodies[name], ctx, idempotency_ttl_s=TTL)
                    assert expected in ei.value.reason_codes, (
                        f"{name}: expected {expected!r}, got {ei.value.reason_codes}"
                    )

    run_async(scenario())


def test_build_toolbelt_registers_the_full_set() -> None:
    """Registry construction is DB-free (preconditions/invoke touch the DB, construction does not),
    so the full set is assertable without a database."""
    registry = build_toolbelt(gateway=None, run_machine=_FakeRunMachine())  # type: ignore[arg-type]
    assert set(registry.names()) == set(_MATRIX)
    assert len(registry) == 17


def test_duplicate_tool_registration_is_impossible_by_construction() -> None:
    # build_toolbelt registers each tool type exactly once; a second build is an independent
    # registry (no shared mutable state), so two builds never collide.
    a = build_toolbelt(gateway=None, run_machine=_FakeRunMachine())  # type: ignore[arg-type]
    b = build_toolbelt(gateway=None, run_machine=_FakeRunMachine())  # type: ignore[arg-type]
    assert a is not b
    assert a.names() == b.names()
