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
_DISCOVERY_CONFIGURATION_REVISION = "064ad0f43519"
_PILOT_HEAD = "0974f1d29e79"
_ONBOARDING_HEAD = "2500c418396f"


def _script_directory() -> ScriptDirectory:
    config = Config(str(_REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def test_discovery_configuration_is_on_the_single_head_lineage_after_the_explicit_gate_merge() -> (
    None
):
    """The gate-merge lineage is intact and the graph still has exactly one head.

    This used to pin ``064ad0f43519`` as *the* head. It is no longer the tip — later branches
    (the part-iii design/platform merge, then the comprehensive account/committee research
    merge) chained off it — and re-pinning the literal tip would make every future migration
    break this test for reasons that have nothing to do with the gate contract. What the
    conventions in ``CLAUDE.md`` actually require is "exactly one head, always"; what *this*
    test owns is the explicit-gate lineage below it. So it asserts both, the same shape as
    ``tests/design/test_design_schema_db.py::test_single_alembic_head_descending_from_the_ratified_base``:
    one head, and the discovery-configuration revision is an ancestor of it.
    """

    scripts = _script_directory()
    heads = scripts.get_heads()
    assert len(heads) == 1, f"expected exactly one alembic head, got {heads}"
    lineage = {revision.revision for revision in scripts.iterate_revisions(heads[0], "base")}
    assert _DISCOVERY_CONFIGURATION_REVISION in lineage, (
        f"head {heads[0]} does not descend from {_DISCOVERY_CONFIGURATION_REVISION}"
    )
    assert (
        scripts.get_revision(_DISCOVERY_CONFIGURATION_REVISION).down_revision  # type: ignore[union-attr]
        == _UNIFIED_REVISION
    )
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
            discovery_triggers = set(
                (
                    await conn.execute(
                        text(
                            "SELECT tgname FROM pg_trigger "
                            "WHERE tgrelid='project_run_discovery_configuration'::regclass "
                            "AND NOT tgisinternal"
                        )
                    )
                )
                .scalars()
                .all()
            )
            discovery_validator = str(
                (
                    await conn.execute(
                        text(
                            "SELECT pg_get_functiondef(oid) FROM pg_proc "
                            "WHERE proname='project_run_discovery_configuration_validate'"
                        )
                    )
                ).scalar_one()
            )
            discovery_immutability = str(
                (
                    await conn.execute(
                        text(
                            "SELECT pg_get_triggerdef(oid) FROM pg_trigger "
                            "WHERE tgname='project_run_discovery_configuration_immutable'"
                        )
                    )
                ).scalar_one()
            )

        for kind in (
            "directive_confirmation",
            "icp_confirmation",
            "product_selection",
            "product_set_selection",
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
            "presented.kind = 'product_set_selection'",
            "selected_option_refs",
            "candidate ->> 'product_id' = chosen.value",
            "subject_kind",
            "discovery_configuration",
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
        assert {
            "project_run_discovery_configuration_authority",
            "project_run_discovery_configuration_immutable",
        } <= discovery_triggers
        for enforced_fragment in (
            "stage0-discovery-configuration@1",
            "requested_account_count",
            "NOT BETWEEN 1 AND 50",
            "jsonb_array_elements",
            "count(DISTINCT criterion)",
            "snapshot_erased_at IS NOT NULL",
            "source_answer.expected_subject_sha256",
            "source_answer.answered_by_user_id",
        ):
            assert enforced_fragment in discovery_validator
        assert "BEFORE DELETE OR UPDATE" in discovery_immutability

    run_async(scenario())
