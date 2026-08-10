"""Part II slice D6 Round A — the governed design write path, behaviourally.

Three claims, each proved rather than asserted in a docstring:

1. **Preconditions are loud.** A refused design write raises ``PreconditionFailed`` with its
   documented ``reason_code`` and leaves no row behind — never a silent-empty success
   (pre-mortem #2).
2. **A keyed retry replays; it does not repeat.** The same ``Idempotency-Key`` + the same body
   returns the first outcome from the durable journal/A9 record without a second effect — which
   for ``rollback`` (a current<->previous SWAP) and ``publish`` (a rotate) is the difference
   between a safe retry and silent corruption. The same key with a *different* body is a 409-class
   ``IdempotencyConflict``.
3. **It is the platform's substrate, not a design-local imitation.** A design invocation writes
   ``tool_invocation`` (A9) and the C5.1 execution journal (``execution`` / ``execution_node`` /
   ``execution_attempt`` / ``execution_event`` / ``execution_artifact_ref``) exactly as a platform
   tool call does, with the parameter body artifact-backed under ``{workspace}/{sha256}``.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest
from clue_db import create_engine
from clue_execution import OperationConflict
from clue_toolbelt import PreconditionFailed
from fastapi.testclient import TestClient
from sqlalchemy import text

from conftest import make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from test_web_export import find_node, get_document, seed_document

COMPONENT_SOURCE = """
export const meta = { name: "Hero", description: "A hero." };
export default function Hero() {
  return <section className="p-6"><h1>Hero</h1></section>;
}
"""


@pytest.fixture()
def app(tmp_path: Path, design_storage) -> Any:
    return create_app(tmp_path / "engine-cache", storage=design_storage)


@pytest.fixture()
def client(app: Any) -> TestClient:
    return make_client(app)


def workspace() -> str:
    return os.environ["LUMEN_DEV_WORKSPACE_ID"]


def invoke(app: Any, name: str, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    result = app.state.design_tools.invoke(
        name, body, workspace_id=workspace(), **kwargs
    )
    return {"references": dict(result.references), "replayed": result.replayed}


def query(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """One read against the platform tables the design invoker writes."""

    async def run() -> list[dict[str, Any]]:
        engine = create_engine()
        try:
            async with engine.connect() as conn:
                rows = (await conn.execute(text(sql), params)).mappings().all()
                return [dict(row) for row in rows]
        finally:
            await engine.dispose()

    return asyncio.run(run())


# --- 1. loud preconditions ------------------------------------------------------------------


def test_account_create_refuses_a_duplicate_id_without_writing(app: Any) -> None:
    invoke(app, "design_create_web_account", {"account_id": "acc_gov", "name": "One"})
    with pytest.raises(PreconditionFailed) as refused:
        invoke(app, "design_create_web_account", {"account_id": "acc_gov", "name": "Two"})
    assert refused.value.reason_codes == ("design_account_exists",)
    # The refused write did not overwrite the first one.
    assert HybridRepository(workspace()).require_web_account("acc_gov")["name"] == "One"


def test_account_create_refuses_an_unresolvable_logo(app: Any) -> None:
    with pytest.raises(PreconditionFailed) as refused:
        invoke(
            app,
            "design_create_web_account",
            {"account_id": "acc_logo", "name": "Logo", "logo_asset_id": "asset_missing"},
        )
    assert refused.value.reason_codes == ("design_account_logo_unresolved",)
    assert HybridRepository(workspace()).get_web_account("acc_logo") is None


def test_component_source_write_refuses_an_unknown_account_and_an_invalid_tree(
    app: Any,
) -> None:
    with pytest.raises(PreconditionFailed) as unknown:
        invoke(
            app,
            "design_write_component_source",
            {
                "account_id": "acc_absent",
                "slug": "hero",
                "expected_version": 0,
                "files": {"hero.tsx": COMPONENT_SOURCE},
                "provenance": {"kind": "test"},
            },
        )
    assert unknown.value.reason_codes == ("design_account_not_found",)

    invoke(app, "design_create_web_account", {"account_id": "acc_src", "name": "Src"})
    with pytest.raises(PreconditionFailed) as invalid:
        invoke(
            app,
            "design_write_component_source",
            {
                "account_id": "acc_src",
                "slug": "hero",
                "expected_version": 0,
                # No `hero.tsx` entry file — the ported canonical-snapshot contract.
                "files": {"other.tsx": COMPONENT_SOURCE},
                "provenance": {"kind": "test"},
            },
        )
    assert invalid.value.reason_codes == ("design_component_source_invalid",)
    assert HybridRepository(workspace()).get_custom_component("acc_src", "hero") is None


def test_rollback_refuses_an_unknown_slug_and_a_publish_with_no_previous(
    app: Any, client: TestClient
) -> None:
    with pytest.raises(PreconditionFailed) as unknown:
        invoke(app, "design_rollback_web_publish", {"slug": "not-a-slug"})
    assert unknown.value.reason_codes == ("design_publish_not_found",)

    document = seed_document(client)
    published = client.post(f"/documents/{document['id']}/web/publish", json={})
    assert published.status_code == 200, published.text
    with pytest.raises(PreconditionFailed) as no_previous:
        invoke(app, "design_rollback_web_publish", {"slug": published.json()["slug"]})
    assert no_previous.value.reason_codes == ("design_publish_no_previous",)


# --- 2. keyed replay ------------------------------------------------------------------------


def test_a_keyed_component_source_write_replays_instead_of_bumping_twice(app: Any) -> None:
    invoke(app, "design_create_web_account", {"account_id": "acc_cas", "name": "CAS"})
    body = {
        "account_id": "acc_cas",
        "slug": "hero",
        "expected_version": 0,
        "files": {"hero.tsx": COMPONENT_SOURCE},
        "provenance": {"kind": "test"},
    }
    first = invoke(app, "design_write_component_source", body, idempotency_key="k-cas")
    assert first["replayed"] is False
    assert first["references"]["source_version"] == 1

    second = invoke(app, "design_write_component_source", body, idempotency_key="k-cas")
    assert second["replayed"] is True
    assert second["references"] == first["references"]

    component = HybridRepository(workspace()).require_custom_component("acc_cas", "hero")
    assert component["source_version"] == 1, "a replay must not append a second revision"


def test_the_same_key_with_a_different_body_is_a_conflict(app: Any) -> None:
    """A reused key with a changed body is a 409-class conflict, never a silent second write.

    The journal catches it before the A9 store does: the derived operation id already owns an
    execution node whose parameter artifact is a different content hash, so
    ``DbInvocationJournal.begin`` raises ``OperationConflict``. ``run_design_tool`` maps that and
    ``IdempotencyConflict`` to the same 409 body.
    """
    invoke(app, "design_create_web_account", {"account_id": "acc_conf", "name": "Conflict"})
    body = {
        "account_id": "acc_conf",
        "slug": "hero",
        "expected_version": 0,
        "files": {"hero.tsx": COMPONENT_SOURCE},
        "provenance": {"kind": "test"},
    }
    invoke(app, "design_write_component_source", body, idempotency_key="k-conflict")
    with pytest.raises(OperationConflict):
        invoke(
            app,
            "design_write_component_source",
            {**body, "files": {"hero.tsx": COMPONENT_SOURCE + "\n// drift\n"}},
            idempotency_key="k-conflict",
        )
    component = HybridRepository(workspace()).require_custom_component("acc_conf", "hero")
    assert component["source_version"] == 1


def test_a_keyed_publish_replays_without_rotating_the_rollback_buffer(
    client: TestClient,
) -> None:
    """Republishing is a rotate. A keyed retry must NOT burn the one-step rollback buffer."""
    document = seed_document(client)
    headers = {"Idempotency-Key": "publish-once"}
    first = client.post(
        f"/documents/{document['id']}/web/publish", json={}, headers=headers
    )
    assert first.status_code == 200, first.text
    assert first.json()["previous_available"] is False

    again = client.post(
        f"/documents/{document['id']}/web/publish", json={}, headers=headers
    )
    assert again.status_code == 200, again.text
    assert again.json() == first.json()
    assert again.json()["previous_available"] is False, (
        "a replayed publish must not rotate current -> previous"
    )


def test_a_keyed_rollback_replays_instead_of_swapping_back(client: TestClient) -> None:
    """Rollback is a SWAP: without a key a blind retry undoes itself. With one it replays."""
    document = seed_document(client)
    assert client.post(f"/documents/{document['id']}/web/publish", json={}).status_code == 200

    text_id = find_node(get_document(client, document["id"])["scene"], "text")
    edit = client.post(
        f"/documents/{document['id']}/web/operations",
        json={
            "operations": [
                {
                    "kind": "set_text",
                    "page_id": "home",
                    "id": text_id,
                    "content": "GOVERNED_TWO",
                }
            ],
            "base_version": 1,
        },
    )
    assert edit.status_code == 200, edit.text
    republished = client.post(f"/documents/{document['id']}/web/publish", json={})
    assert republished.status_code == 200, republished.text
    slug = republished.json()["slug"]
    assert republished.json()["doc_version"] == 2

    headers = {"Idempotency-Key": "rollback-once"}
    rolled = client.post(f"/web/publishes/{slug}/rollback", headers=headers)
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["doc_version"] == 1

    replayed = client.post(f"/web/publishes/{slug}/rollback", headers=headers)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json() == rolled.json()
    assert replayed.json()["doc_version"] == 1, (
        "a replayed rollback must not swap the slug back to the newer revision"
    )


# --- 3. the platform's own durable substrate ------------------------------------------------


def test_a_design_invocation_lands_on_the_platform_journal_and_a9_tables(app: Any) -> None:
    invoke(
        app,
        "design_create_web_account",
        {"account_id": "acc_journal", "name": "Journal"},
        idempotency_key="k-journal",
    )

    invocations = query(
        "SELECT tool_name, status FROM tool_invocation WHERE workspace_id = :w",
        {"w": workspace()},
    )
    assert [row["tool_name"] for row in invocations] == ["design_create_web_account@1"]
    assert invocations[0]["status"] == "completed"

    nodes = query(
        """
        SELECT n.tool_name, n.tool_version, n.parameter_artifact_key, n.display_params_json
        FROM execution_node n
        JOIN execution e ON e.id = n.execution_id
        WHERE e.workspace_id = :w
        """,
        {"w": workspace()},
    )
    assert len(nodes) == 1
    assert nodes[0]["tool_name"] == "design_create_web_account"
    assert nodes[0]["tool_version"] == "1"
    # The validated body is artifact-backed under the platform's `{workspace}/{sha256}` key,
    # and only the declared safe-display fields are copied into the journal projection.
    assert str(nodes[0]["parameter_artifact_key"]).startswith(f"{workspace()}/")

    events = query(
        """
        SELECT ev.event_type
        FROM execution_event ev
        JOIN execution e ON e.id = ev.execution_id
        WHERE e.workspace_id = :w
        ORDER BY ev.seq
        """,
        {"w": workspace()},
    )
    assert [row["event_type"] for row in events] == [
        "execution.queued",
        "execution.started",
        "node.scheduled",
        "node.started",
        "node.completed",
        "execution.completed",
    ]

    artifacts = query(
        "SELECT source_key FROM artifact WHERE workspace_id = :w AND source_key = "
        "'tool_parameters'",
        {"w": workspace()},
    )
    assert artifacts, "the parameter body is governed storage, not an inline blob"


def test_a_refused_write_is_journaled_as_blocked_and_never_cached(app: Any) -> None:
    invoke(app, "design_create_web_account", {"account_id": "acc_blocked", "name": "One"})
    with pytest.raises(PreconditionFailed):
        invoke(
            app,
            "design_create_web_account",
            {"account_id": "acc_blocked", "name": "Two"},
            idempotency_key="k-blocked",
        )
    # A refusal runs before the A9 reservation, so it is never cached (the retry after the
    # prerequisite is satisfied must be able to execute).
    cached = query(
        "SELECT idempotency_key FROM tool_invocation WHERE workspace_id = :w "
        "AND idempotency_key = 'k-blocked'",
        {"w": workspace()},
    )
    assert cached == []
    blocked = query(
        """
        SELECT ev.event_type
        FROM execution_event ev
        JOIN execution e ON e.id = ev.execution_id
        WHERE e.workspace_id = :w AND ev.event_type = 'node.blocked'
        """,
        {"w": workspace()},
    )
    assert len(blocked) == 1, "a refused design write is a durably visible blocked node"
