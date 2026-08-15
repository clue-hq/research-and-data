"""Migration-graph and installed-schema guards for the unified human-gate contract."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from clue_db import db_lifespan

from .conftest import run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MERGE_REVISION = "fea2a60cffc0"
_UNIFIED_REVISION = "f85ca69b93ba"
_PILOT_HEAD = "0974f1d29e79"
_ONBOARDING_HEAD = "2500c418396f"


def _script_directory() -> ScriptDirectory:
    config = Config(str(_REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def test_unified_gate_revision_is_the_only_head_and_has_an_explicit_merge_parent() -> None:
    scripts = _script_directory()
    assert scripts.get_heads() == [_UNIFIED_REVISION]
    assert scripts.get_revision(_UNIFIED_REVISION).down_revision == _MERGE_REVISION  # type: ignore[union-attr]
    merge = scripts.get_revision(_MERGE_REVISION)
    assert merge is not None
    assert set(merge.down_revision) == {_PILOT_HEAD, _ONBOARDING_HEAD}


@pytest.mark.usefixtures("require_db")
def test_installed_gate_constraints_and_trigger_are_the_combined_contract() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            constraints = {
                str(row.conname): str(row.definition)
                for row in (
                    await conn.execute(
                        text(
                            "SELECT conname, pg_get_constraintdef(oid) AS definition "
                            "FROM pg_constraint WHERE conname IN ("
                            "'agent_gate_kind', 'agent_gate_permitted_decisions', "
                            "'agent_gate_amount_pair', 'agent_gate_answer_selection_valid')"
                        )
                    )
                ).all()
            }
            validator = str(
                (
                    await conn.execute(
                        text(
                            "SELECT pg_get_functiondef(oid) FROM pg_proc "
                            "WHERE proname='agent_gate_answer_validate'"
                        )
                    )
                ).scalar_one()
            )
            triggers = set(
                (
                    await conn.execute(
                        text(
                            "SELECT tgname FROM pg_trigger "
                            "WHERE tgrelid='agent_gate_answer'::regclass AND NOT tgisinternal"
                        )
                    )
                )
                .scalars()
                .all()
            )

        for kind in (
            "directive_confirmation",
            "icp_confirmation",
            "product_selection",
            "plan_approval",
            "budget_approval",
        ):
            assert kind in constraints["agent_gate_kind"]
        assert "permitted_decisions" in constraints["agent_gate_permitted_decisions"]
        assert "max_spend_cents IS NULL" in constraints["agent_gate_amount_pair"]
        assert "currency IS NULL" in constraints["agent_gate_amount_pair"]
        assert "decision_payload = '{}'::jsonb" in constraints["agent_gate_answer_selection_valid"]

        for enforced_fragment in (
            "snapshot_erased_at",
            "ANY(presented.permitted_decisions)",
            "expected_subject_sha256 <> presented.expected_subject_sha256",
            "answered_by_user_id <> presented.addressee_user_id",
            "an answer cannot carry both a revision payload and a selection",
            "revision_request",
            "NOT BETWEEN 1 AND 4000",
            "presented.kind = 'product_selection'",
            "jsonb_array_elements",
            "candidate ->> 'product_id' = NEW.selected_option_ref",
            "answering_turn.project_id <> presented.project_id",
            "answering_turn.thread_id <> presented.thread_id",
        ):
            assert enforced_fragment in validator
        assert {
            "agent_gate_answer_append_only",
            "agent_gate_answer_authority",
            "agent_gate_answer_snapshot_available",
        } <= triggers

    run_async(scenario())
