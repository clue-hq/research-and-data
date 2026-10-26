"""CRM integration Phase 2: the schema for governed CRM writes.

Proposals, the write log, standing permissions (grants), record links, the
``crm_write_permission`` gate kind and its answer rules, the ``crm_writes_finished`` wake, and
the ``crm_write`` fleet kind (spec docs/superpowers/specs/crm-integration/, Phase 2 plan Task 2).

The round trip commits real rows to the throwaway DB, downgrades past the foundation migration
(which deletes the rows of the new gate kind and derivation first), and upgrades again, so the
DB is always left at head.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_fleet import FleetTaskKind
from tests._workspace import seed_project

from .conftest import run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VERSIONS = _REPO_ROOT / "alembic" / "versions"
_PREVIOUS_REVISION = "c87ba03cfc4e"
_SHA = "e" * 64
_TABLES = ("crm_write_proposal", "crm_write", "crm_write_grant", "crm_record_link")


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


def _migration_module(prefix: str) -> Any:
    (path,) = _VERSIONS.glob(f"{prefix}_*.py")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalized_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_the_validator_without_the_crm_branch_is_the_previous_migrations_text() -> None:
    """downgrade() must reinstall exactly what 0aa95f87eb49 installed — proven by text."""
    (path,) = _VERSIONS.glob("*_crm_write_foundation.py")
    foundation = _migration_module(path.stem.split("_")[0])
    previous = _migration_module("0aa95f87eb49")
    assert _normalized_sql(foundation._answer_validator(crm_write=False)) == _normalized_sql(
        previous._answer_validator(product_set=True)
    )


# --- seeding --------------------------------------------------------------------------------


async def _artifact(conn: AsyncConnection, ws: str) -> str:
    key = f"{ws}/{_SHA}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            "size_bytes) VALUES (:key, :ws, :sha, 'text/plain', 3) "
            "ON CONFLICT (storage_key) DO NOTHING"
        ),
        {"key": key, "ws": ws, "sha": _SHA},
    )
    return key


async def _submission(
    conn: AsyncConnection,
    seeded: dict[str, Any],
    *,
    derivation: str | None = None,
    derived_from: UUID | None = None,
) -> UUID:
    turn_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO agent_turn_submission (turn_id, workspace_id, project_id, thread_id, "
            "submitted_by_user_id, submitted_via_membership_id, onboarding_input_id, "
            "message_artifact_key, message_sha256, derivation, derived_from_turn_id) "
            "VALUES (:turn, :ws, :project, :thread, :user, :membership, :onb, :key, :sha, "
            ":derivation, :derived_from)"
        ),
        {
            "turn": turn_id,
            "ws": seeded["ws"],
            "project": seeded["project"],
            "thread": seeded["thread"],
            "user": seeded["user"],
            "membership": seeded["membership"],
            "onb": seeded["onb"],
            "key": seeded["key"],
            "sha": _SHA,
            "derivation": derivation,
            "derived_from": derived_from,
        },
    )
    return turn_id


async def _seed_chain(conn: AsyncConnection) -> dict[str, Any]:
    """Workspace → project → thread → user → presenting agent turn → one user submission."""
    ws = f"ws_crm_write_{uuid4().hex[:8]}"
    project = await seed_project(conn, ws, name="CRM writes")
    key = await _artifact(conn, ws)
    onb = uuid4()
    await conn.execute(
        text(
            "INSERT INTO onboarding_input (id, workspace_id, brand_id, kind, artifact_key, "
            "content_sha256, actor) VALUES (:id, :ws, :brand, 'user_turn', :key, :sha, 'human')"
        ),
        {"id": onb, "ws": ws, "brand": project.brand_id, "key": key, "sha": _SHA},
    )
    thread = f"thr_crm_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :p)"),
        {"id": thread, "ws": ws, "p": project.project_id},
    )
    user = f"user_crm_{uuid4().hex[:8]}"
    membership = f"member_crm_{uuid4().hex[:8]}"
    await conn.execute(text("INSERT INTO platform_user (user_id) VALUES (:u)"), {"u": user})
    await conn.execute(
        text(
            "INSERT INTO workspace_membership (membership_id, workspace_id, user_id, role_key, "
            "status, activated_at) VALUES (:m, :ws, :u, 'owner', 'active', now())"
        ),
        {"m": membership, "ws": ws, "u": user},
    )
    execution = uuid4()
    await conn.execute(
        text(
            "INSERT INTO execution (id, workspace_id, project_id, started_by, "
            "parameter_manifest_hash, pin_manifest_hash) "
            "VALUES (:id, :ws, :p, 'human', :h, :h)"
        ),
        {"id": execution, "ws": ws, "p": project.project_id, "h": "0" * 64},
    )
    agent_turn = uuid4()
    await conn.execute(
        text(
            "INSERT INTO agent_turn (id, execution_id, workspace_id, project_id, thread_id, "
            " actor_id, role, workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, resource_manifest_sha256, "
            " retention_class, requested_at) "
            "VALUES (:id, :e, :ws, :p, :t, 'actor-1', 'head_of_abm', 'root-1', 'head-of-abm', "
            " 'v1', :h, :key, :sha, :h, 'standard', now())"
        ),
        {
            "id": agent_turn,
            "e": execution,
            "ws": ws,
            "p": project.project_id,
            "t": thread,
            "h": "0" * 64,
            "key": key,
            "sha": _SHA,
        },
    )
    seeded: dict[str, Any] = {
        "ws": ws,
        "project": project.project_id,
        "thread": thread,
        "user": user,
        "membership": membership,
        "onb": onb,
        "key": key,
        "agent_turn": agent_turn,
    }
    seeded["answering_turn"] = await _submission(conn, seeded)
    connection_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO workspace_integration_connection (connection_id, workspace_id, provider, "
            "composio_connected_account_id, composio_auth_config_id, status, connected_by_user_id) "
            "VALUES (:id, :ws, 'hubspot', :acct, 'ac_test', 'active', :u)"
        ),
        {"id": connection_id, "ws": ws, "acct": f"ca_{uuid4().hex[:8]}", "u": user},
    )
    seeded["connection"] = connection_id
    return seeded


async def _gate(conn: AsyncConnection, seeded: dict[str, Any]) -> UUID:
    gate_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO agent_gate (gate_id, workspace_id, project_id, thread_id, turn_id, kind, "
            " subject_ref, expected_subject_sha256, subject_snapshot, permitted_decisions, "
            " addressee_user_id) "
            "VALUES (:g, :ws, :p, :t, :turn, 'crm_write_permission', :subject, :sha, "
            " CAST(:snapshot AS jsonb), ARRAY['approved', 'rejected'], :u)"
        ),
        {
            "g": gate_id,
            "ws": seeded["ws"],
            "p": seeded["project"],
            "t": seeded["thread"],
            "turn": seeded["agent_turn"],
            "subject": f"crm_write_proposal:{uuid4()}",
            "sha": _SHA,
            "snapshot": json.dumps({"writes": []}),
            "u": seeded["user"],
        },
    )
    return gate_id


async def _answer(
    conn: AsyncConnection,
    seeded: dict[str, Any],
    gate_id: UUID,
    *,
    decision: str,
    payload: Any,
) -> None:
    turn = seeded["answering_turn"]
    await conn.execute(
        text(
            "INSERT INTO agent_gate_answer (gate_id, workspace_id, turn_id, action_ref, decision, "
            " expected_subject_sha256, decision_payload, answered_by_user_id) "
            "VALUES (:g, :ws, :turn, :action, :decision, :sha, CAST(:payload AS jsonb), :u)"
        ),
        {
            "g": gate_id,
            "ws": seeded["ws"],
            "turn": turn,
            "action": f"turn-action:{turn}",
            "decision": decision,
            "sha": _SHA,
            "payload": json.dumps(payload),
            "u": seeded["user"],
        },
    )


async def _refused(conn: AsyncConnection, body: Any, match: str) -> None:
    nested = await conn.begin_nested()
    with pytest.raises((DBAPIError, IntegrityError), match=match):
        await body()
    await nested.rollback()


# --- the round trip -------------------------------------------------------------------------


async def _write_rows() -> dict[str, Any]:
    async with db_lifespan() as engine, engine.connect() as conn:
        tx = await conn.begin()
        seeded = await _seed_chain(conn)
        ws, connection = seeded["ws"], seeded["connection"]

        # A gate of the new kind; its answer is checked by the trigger.
        approved_gate = await _gate(conn, seeded)
        write_ids = [str(uuid4())]
        for payload in (
            {"selected_write_ids": write_ids, "always_allow": [], "note": "x"},
            {"selected_write_ids": write_ids},
            {"always_allow": []},
            {"selected_write_ids": "all", "always_allow": []},
            {},
        ):
            await _refused(
                conn,
                lambda payload=payload: _answer(
                    conn, seeded, approved_gate, decision="approved", payload=payload
                ),
                "CRM write permission",
            )
        await _answer(
            conn,
            seeded,
            approved_gate,
            decision="approved",
            payload={"selected_write_ids": write_ids, "always_allow": ["field:update:deal:amount"]},
        )
        rejected_gate = await _gate(conn, seeded)
        await _refused(
            conn,
            lambda: _answer(
                conn,
                seeded,
                rejected_gate,
                decision="rejected",
                payload={"selected_write_ids": [], "always_allow": []},
            ),
            "CRM write permission",
        )
        await _answer(conn, seeded, rejected_gate, decision="rejected", payload={})

        # The wake.
        await _submission(
            conn,
            seeded,
            derivation="crm_writes_finished",
            derived_from=seeded["answering_turn"],
        )

        # A proposal, a write, a grant, a record link.
        proposal = uuid4()
        await conn.execute(
            text(
                "INSERT INTO crm_write_proposal (proposal_id, workspace_id, connection_id, "
                "project_id, thread_id, turn_id, gate_id, status) "
                "VALUES (:id, :ws, :c, :p, :t, :turn, :g, 'awaiting_permission')"
            ),
            {
                "id": proposal,
                "ws": ws,
                "c": connection,
                "p": seeded["project"],
                "t": seeded["thread"],
                "turn": seeded["agent_turn"],
                "g": approved_gate,
            },
        )

        async def write(**overrides: Any) -> UUID:
            write_id = uuid4()
            row = {
                "id": write_id,
                "proposal": proposal,
                "ws": ws,
                "c": connection,
                "ordinal": 0,
                "status": "failed",
                "failure_kind": "not_applied",
                "covered_by": f"gate:{approved_gate}",
                "key": f"crm-write:{write_id}",
            } | overrides
            await conn.execute(
                text(
                    "INSERT INTO crm_write (write_id, proposal_id, workspace_id, connection_id, "
                    "ordinal, slug, arguments, kind, object, record_ref, record_label, field, "
                    "before_value, after_value, overwrites_person, reason, scope_key, covered_by, "
                    "selected, status, failure_kind, idempotency_key) "
                    "VALUES (:id, :proposal, :ws, :c, :ordinal, 'HUBSPOT_UPDATE_DEAL', "
                    "CAST('{\"amount\": 5}' AS jsonb), 'update', 'deal', 'deal-1', 'Acme deal', "
                    "'amount', CAST('4' AS jsonb), CAST('5' AS jsonb), true, 'new quote', "
                    "'field:update:deal:amount', :covered_by, true, :status, :failure_kind, :key)"
                ),
                row,
            )
            return write_id

        write_id = await write()
        await _refused(conn, lambda: write(ordinal=1, status="done"), "crm_write_status")
        await _refused(
            conn, lambda: write(ordinal=1, failure_kind="timeout"), "crm_write_failure_kind"
        )
        await _refused(conn, lambda: write(ordinal=1, covered_by="me"), "crm_write_covered_by")
        await _refused(conn, lambda: write(), "crm_write_proposal_ordinal")

        async def grant(scope_kind: str, field: str | None) -> None:
            await conn.execute(
                text(
                    "INSERT INTO crm_write_grant (grant_id, workspace_id, connection_id, "
                    "scope_kind, kind, object, field, granted_by_user_id) "
                    "VALUES (:id, :ws, :c, :scope, :kind, :object, :field, :u)"
                ),
                {
                    "id": uuid4(),
                    "ws": ws,
                    "c": connection,
                    "scope": scope_kind,
                    "kind": None if scope_kind == "fully_automatic" else "update",
                    "object": None if scope_kind == "fully_automatic" else "deal",
                    "field": field,
                    "u": seeded["user"],
                },
            )

        await grant("field", "amount")
        await grant("fully_automatic", None)
        await _refused(conn, lambda: grant("field", "amount"), "crm_write_grant_one_live")
        await _refused(conn, lambda: grant("fully_automatic", None), "crm_write_grant_one_live")
        await _refused(conn, lambda: grant("everything", None), "crm_write_grant_scope_kind")

        await conn.execute(
            text(
                "INSERT INTO crm_record_link (workspace_id, connection_id, crm_object, crm_id, "
                "created_by_clue, created_by_write_id) VALUES (:ws, :c, 'deal', 'deal-1', "
                "true, :w)"
            ),
            {"ws": ws, "c": connection, "w": write_id},
        )
        await tx.commit()
        return {"ws": ws, "gates": [approved_gate, rejected_gate]}


async def _state(ws: str) -> dict[str, Any]:
    async with db_lifespan() as engine, engine.connect() as conn:
        tables = {
            t: (await conn.execute(text("SELECT to_regclass(:t)"), {"t": t})).scalar_one()
            for t in _TABLES
        }
        gates = (
            await conn.execute(
                text("SELECT count(*) FROM agent_gate WHERE workspace_id = :ws"), {"ws": ws}
            )
        ).scalar_one()
        wakes = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM agent_turn_submission "
                    "WHERE workspace_id = :ws AND derivation IS NOT NULL"
                ),
                {"ws": ws},
            )
        ).scalar_one()
        checks = {
            str(row.conname): str(row.definition)
            for row in await conn.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint "
                    "WHERE conname IN ('agent_gate_kind', 'agent_turn_submission_derivation_kind')"
                )
            )
        }
        return {"tables": tables, "gates": gates, "wakes": wakes, "checks": checks}


@pytest.mark.usefixtures("require_db")
def test_crm_write_foundation_round_trips() -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    try:
        written = run_async(_write_rows())
        at_head = run_async(_state(written["ws"]))
        assert all(at_head["tables"].values())
        assert at_head["gates"] == 2
        assert at_head["wakes"] == 1
        assert "crm_write_permission" in at_head["checks"]["agent_gate_kind"]
        assert "crm_writes_finished" in at_head["checks"]["agent_turn_submission_derivation_kind"]

        command.downgrade(cfg, _PREVIOUS_REVISION)
        below = run_async(_state(written["ws"]))
        assert not any(below["tables"].values())
        assert below["gates"] == 0
        assert below["wakes"] == 0
        assert "crm_write_permission" not in below["checks"]["agent_gate_kind"]
        assert "crm_writes_finished" not in below["checks"]["agent_turn_submission_derivation_kind"]
    finally:
        command.upgrade(cfg, "head")
    assert all(run_async(_state("none"))["tables"].values())


@pytest.mark.usefixtures("require_db")
def test_the_fleet_kind_enum_has_crm_write_last_and_matches_the_db() -> None:
    async def scenario() -> list[str]:
        async with db_lifespan() as engine, engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'fleet_task_kind' ORDER BY e.enumsortorder"
                )
            )
            return [str(r.enumlabel) for r in rows]

    labels = run_async(scenario())
    assert labels[-1] == "crm_write"
    assert labels == [k.value for k in FleetTaskKind]
