"""P6.1 canonical custom-component nodes and immutable account registry."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_client
from sqlalchemy import text as sa_text
from sqlalchemy.exc import DBAPIError

from lumen_api.custom_components import (
    persist_compiled_custom_component_artifact,
    resolve_custom_component_artifact_blob,
)
from lumen_api.design_store import HybridRepository
from lumen_api.database import NotFoundError
from lumen_api.main import create_app


COMPONENT_HTML = """
<section id="hero">
  <div id="left"><p>Left</p></div>
  <div id="right"><p>Right</p></div>
</section>
"""


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return make_client(create_app(tmp_path / "api.sqlite3"))


def create_account(client: TestClient, account_id: str) -> dict:
    response = client.post(
        "/web/accounts",
        json={"account_id": account_id, "name": account_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def persist_artifact(
    client: TestClient,
    tmp_path: Path,
    *,
    account_id: str,
    slug: str = "book-a-call",
    suffix: bytes = b"v1",
) -> dict:
    repository = HybridRepository()
    return persist_compiled_custom_component_artifact(
        repository,
        tmp_path / "custom-component-store",
        account_id=account_id,
        slug=slug,
        source=b"export default function Component() {} //" + suffix,
        bundle=b"export default function Component() {} //" + suffix,
        manifest={"schema_version": 1, "entry": "index.tsx"},
        provenance={
            "kind": "test_fixture_compiler",
            "compiler_version": "fixture-v1",
            "input": suffix.decode(),
        },
    )


def create_account_document(client: TestClient, account_id: str) -> dict:
    document_id = f"doc_{account_id}"
    empty = client.app.state.core.web_new_doc(document_id, "Component fixture", None)[
        "web_doc"
    ]
    ingested = client.app.state.core.web_ingest_html(
        empty, "home", COMPONENT_HTML, None, None
    )
    assert ingested.get("web_doc"), ingested
    repository = HybridRepository()
    return repository.create_document(
        ingested["web_doc"],
        doc_kind="web",
        account_id=account_id,
    )


def page_containers(web_doc: dict) -> list[str]:
    return [
        node_id
        for node_id, node in web_doc["pages"][0]["nodes"].items()
        if node["kind"] == "container"
    ]


def custom_node(artifact: dict, node_id: str = "cc_booking") -> dict:
    return {
        "id": node_id,
        "kind": "custom_component",
        "slug": artifact["slug"],
        "artifact_id": artifact["artifact_id"],
        "props": {
            "headline": "Book a call",
            "showLogo": True,
            "step": 2,
        },
        "classes": "w-[420px] h-[200px]",
    }


def apply(client: TestClient, document_id: str, base_version: int, operation: dict):
    return client.post(
        f"/documents/{document_id}/web/operations",
        json={
            "base_version": base_version,
            "intent": operation["kind"],
            "operations": [operation],
        },
    )


def get_document(client: TestClient, document_id: str) -> dict:
    response = client.get(f"/documents/{document_id}")
    assert response.status_code == 200, response.text
    return response.json()


def test_registry_is_content_addressed_immutable_and_account_scoped(
    client: TestClient, tmp_path: Path
) -> None:
    create_account(client, "acc_alpha")
    create_account(client, "acc_beta")
    first = persist_artifact(client, tmp_path, account_id="acc_alpha")
    retry = persist_artifact(client, tmp_path, account_id="acc_alpha")
    second = persist_artifact(
        client, tmp_path, account_id="acc_alpha", suffix=b"v2"
    )

    assert retry == first
    assert second["artifact_id"] != first["artifact_id"]
    assert first["artifact_id"].startswith("ccart_")
    assert len(first["artifact_id"]) == len("ccart_") + 64
    for name in ("source", "bundle"):
        blob = first[name]
        stored = tmp_path / "custom-component-store" / blob["opaque_ref"]
        assert stored.is_file()
        assert stored.stat().st_size == blob["byte_length"]

    repository = HybridRepository()
    resolved, bundle = resolve_custom_component_artifact_blob(
        repository,
        tmp_path / "custom-component-store",
        account_id="acc_alpha",
        artifact_id=first["artifact_id"],
        member="bundle",
    )
    assert resolved == first
    assert bundle.endswith(b"v1")
    with pytest.raises(NotFoundError):
        resolve_custom_component_artifact_blob(
            repository,
            tmp_path / "custom-component-store",
            account_id="acc_beta",
            artifact_id=first["artifact_id"],
            member="bundle",
        )
    # D2.4B: the registry lives on Postgres and stays immutable — enforced by the
    # design_custom_component_artifact no-UPDATE TRIGGER instead of the old SQLite one.
    # Reaching into `_bridge` is deliberate: the mutation must be attempted straight at the
    # table, below the API boundary. `_run` is its own transaction, so the refusal rolls
    # itself back.
    with pytest.raises(DBAPIError, match="immutable"):
        repository._bridge._run(
            lambda conn: conn.execute(
                sa_text(
                    "UPDATE design_custom_component_artifact SET slug = 'mutated'"
                    " WHERE artifact_id = :i AND workspace_id = :w"
                ),
                {"i": first["artifact_id"], "w": repository.workspace_id},
            )
        )

    listing = client.get("/web/accounts/acc_alpha/custom-components")
    assert listing.status_code == 200
    assert listing.json()["components"][0]["artifact_count"] == 2
    family = client.get(
        "/web/accounts/acc_alpha/custom-components/book-a-call"
    )
    assert family.status_code == 200
    assert len(family.json()["component"]["artifacts"]) == 2
    artifact = client.get(
        f"/web/accounts/acc_alpha/custom-component-artifacts/{first['artifact_id']}"
    )
    assert artifact.status_code == 200
    assert artifact.json()["artifact"] == first
    assert (
        client.get(
            f"/web/accounts/acc_beta/custom-component-artifacts/{first['artifact_id']}"
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/web/accounts/acc_alpha/custom-components",
            json={"slug": "fake-success"},
        ).status_code
        == 405
    )


def test_custom_component_round_trips_and_participates_in_edit_history(
    client: TestClient, tmp_path: Path
) -> None:
    create_account(client, "acc_alpha")
    artifact = persist_artifact(client, tmp_path, account_id="acc_alpha")
    next_artifact = persist_artifact(
        client, tmp_path, account_id="acc_alpha", suffix=b"v2"
    )
    document = create_account_document(client, "acc_alpha")
    page = document["scene"]["pages"][0]
    containers = page_containers(document["scene"])
    # jsonb does not preserve object key order (the repo-wide hazard; select nodes
    # by id, never by dict position).
    assert {"left", "right"} <= set(containers), containers
    source_container = "left"
    target_container = "right"

    inserted = apply(
        client,
        document["id"],
        0,
        {
            "kind": "insert_node",
            "page_id": page["id"],
            "parent": source_container,
            "index": len(page["nodes"][source_container].get("children") or []),
            "nodes": [custom_node(artifact)],
            "root": "cc_booking",
        },
    )
    assert inserted.status_code == 200, inserted.text
    current = get_document(client, document["id"])
    stored = current["scene"]["pages"][0]["nodes"]["cc_booking"]
    assert stored == custom_node(artifact)

    repinned = apply(
        client,
        document["id"],
        current["current_version"],
        {
            "kind": "set_node_props",
            "page_id": page["id"],
            "id": "cc_booking",
            "props": {
                "kind": "custom_component",
                "slug": next_artifact["slug"],
                "artifact_id": next_artifact["artifact_id"],
                "props": {
                    "headline": "Choose a time",
                    "showLogo": False,
                    "step": 3,
                },
            },
        },
    )
    assert repinned.status_code == 200, repinned.text
    current = get_document(client, document["id"])
    assert (
        current["scene"]["pages"][0]["nodes"]["cc_booking"]["artifact_id"]
        == next_artifact["artifact_id"]
    )
    undo_repin = client.post(f"/documents/{document['id']}/web/undo")
    assert undo_repin.status_code == 200, undo_repin.text
    assert (
        get_document(client, document["id"])["scene"]["pages"][0]["nodes"][
            "cc_booking"
        ]["artifact_id"]
        != next_artifact["artifact_id"]
    )
    redo_repin = client.post(f"/documents/{document['id']}/web/redo")
    assert redo_repin.status_code == 200, redo_repin.text
    current = get_document(client, document["id"])
    assert (
        current["scene"]["pages"][0]["nodes"]["cc_booking"]["artifact_id"]
        == next_artifact["artifact_id"]
    )
    artifact = next_artifact

    resized = apply(
        client,
        document["id"],
        current["current_version"],
        {
            "kind": "set_node_classes",
            "page_id": page["id"],
            "id": "cc_booking",
            "classes": "w-[560px] h-[300px] rounded-xl",
        },
    )
    assert resized.status_code == 200, resized.text
    current = get_document(client, document["id"])

    moved = apply(
        client,
        document["id"],
        current["current_version"],
        {
            "kind": "move_node",
            "page_id": page["id"],
            "id": "cc_booking",
            "new_parent": target_container,
            "index": 0,
        },
    )
    assert moved.status_code == 200, moved.text
    current = get_document(client, document["id"])
    assert (
        current["scene"]["pages"][0]["nodes"][target_container]["children"][0]
        == "cc_booking"
    )

    duplicate = copy.deepcopy(
        current["scene"]["pages"][0]["nodes"]["cc_booking"]
    )
    duplicate["id"] = "cc_booking_copy"
    copied = apply(
        client,
        document["id"],
        current["current_version"],
        {
            "kind": "insert_node",
            "page_id": page["id"],
            "parent": target_container,
            "index": 1,
            "nodes": [duplicate],
            "root": "cc_booking_copy",
        },
    )
    assert copied.status_code == 200, copied.text
    current = get_document(client, document["id"])
    assert (
        current["scene"]["pages"][0]["nodes"]["cc_booking_copy"]["artifact_id"]
        == artifact["artifact_id"]
    )
    assert (
        current["scene"]["pages"][0]["nodes"]["cc_booking_copy"]["props"]
        == current["scene"]["pages"][0]["nodes"]["cc_booking"]["props"]
    )

    deleted = apply(
        client,
        document["id"],
        current["current_version"],
        {
            "kind": "remove_node",
            "page_id": page["id"],
            "id": "cc_booking_copy",
        },
    )
    assert deleted.status_code == 200, deleted.text
    current = get_document(client, document["id"])
    assert "cc_booking_copy" not in current["scene"]["pages"][0]["nodes"]

    undone = client.post(f"/documents/{document['id']}/web/undo")
    assert undone.status_code == 200, undone.text
    after_undo = get_document(client, document["id"])
    assert (
        after_undo["scene"]["pages"][0]["nodes"]["cc_booking_copy"]["artifact_id"]
        == artifact["artifact_id"]
    )
    redone = client.post(f"/documents/{document['id']}/web/redo")
    assert redone.status_code == 200, redone.text
    after_redo = get_document(client, document["id"])
    assert (
        "cc_booking_copy" not in after_redo["scene"]["pages"][0]["nodes"]
    )

    rendered = client.get(
        f"/documents/{document['id']}/web/render"
        "?bridge=1&nonce=custom-component-123"
    )
    assert rendered.status_code == 200, rendered.text
    html = rendered.json()["html"]
    assert 'data-node-id="cc_booking"' in html
    assert 'data-custom-component-slug="book-a-call"' in html
    assert 'data-custom-component-placeholder="true"' in html
    assert "Custom component unavailable" in html
    movable_capabilities = html.split(
        "var MOVABLE_NODE_IDS = new Set(", maxsplit=1
    )[1].split(");", maxsplit=1)[0]
    resizable_capabilities = html.split(
        "var RESIZABLE_NODE_IDS = new Set(", maxsplit=1
    )[1].split(");", maxsplit=1)[0]
    assert '"cc_booking"' in movable_capabilities
    assert '"cc_booking"' in resizable_capabilities


def test_invalid_unknown_and_cross_account_references_never_commit(
    client: TestClient, tmp_path: Path
) -> None:
    create_account(client, "acc_alpha")
    create_account(client, "acc_beta")
    alpha = persist_artifact(client, tmp_path, account_id="acc_alpha")
    beta = persist_artifact(client, tmp_path, account_id="acc_beta")
    document = create_account_document(client, "acc_alpha")
    page = document["scene"]["pages"][0]
    parent = page_containers(document["scene"])[0]

    cases = [
        (
            custom_node(
                {
                    **alpha,
                    "artifact_id": "ccart_" + "f" * 64,
                }
            ),
            "custom_component.artifact_unresolved",
        ),
        (custom_node(beta), "custom_component.artifact_forbidden"),
        (
            custom_node({**alpha, "slug": "different-slug"}),
            "custom_component.artifact_slug_mismatch",
        ),
    ]
    for index, (node, expected_code) in enumerate(cases):
        node["id"] = f"cc_invalid_{index}"
        response = apply(
            client,
            document["id"],
            0,
            {
                "kind": "insert_node",
                "page_id": page["id"],
                "parent": parent,
                "index": 0,
                "nodes": [node],
                "root": node["id"],
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == expected_code
        assert (
            client.get(f"/documents/{document['id']}").json()["current_version"]
            == 0
        )

    accountless_id = "doc_accountless"
    empty = client.app.state.core.web_new_doc(
        accountless_id, "Accountless fixture", None
    )["web_doc"]
    ingested = client.app.state.core.web_ingest_html(
        empty, "home", COMPONENT_HTML, None, None
    )["web_doc"]
    repository = HybridRepository()
    accountless = repository.create_document(ingested, doc_kind="web")
    accountless_page = accountless["scene"]["pages"][0]
    accountless_parent = page_containers(accountless["scene"])[0]
    no_account = apply(
        client,
        accountless["id"],
        0,
        {
            "kind": "insert_node",
            "page_id": accountless_page["id"],
            "parent": accountless_parent,
            "index": 0,
            "nodes": [custom_node(alpha)],
            "root": "cc_booking",
        },
    )
    assert no_account.status_code == 422
    assert no_account.json()["detail"]["code"] == "custom_component.account_required"

    unsupported = custom_node(alpha, "cc_bad_props")
    unsupported["props"]["nested"] = {"unsafe": True}
    response = apply(
        client,
        document["id"],
        0,
        {
            "kind": "insert_node",
            "page_id": page["id"],
            "parent": parent,
            "index": 0,
            "nodes": [unsupported],
            "root": unsupported["id"],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "web_operations.invalid"

    child = custom_node(alpha, "cc_with_child")
    child["children"] = ["text_inside"]
    response = apply(
        client,
        document["id"],
        0,
        {
            "kind": "insert_node",
            "page_id": page["id"],
            "parent": parent,
            "index": 0,
            "nodes": [
                child,
                {
                    "id": "text_inside",
                    "kind": "text",
                    "variant": "body",
                    "content": "Not allowed",
                    "classes": "",
                },
            ],
            "root": child["id"],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "web_operations.invalid"


def test_leaf_reparent_rejected_and_missing_artifact_stays_editable_placeholder(
    client: TestClient, tmp_path: Path
) -> None:
    create_account(client, "acc_alpha")
    artifact = persist_artifact(client, tmp_path, account_id="acc_alpha")
    document = create_account_document(client, "acc_alpha")
    page = document["scene"]["pages"][0]
    parent = page_containers(document["scene"])[0]
    inserted = apply(
        client,
        document["id"],
        0,
        {
            "kind": "insert_node",
            "page_id": page["id"],
            "parent": parent,
            "index": 0,
            "nodes": [custom_node(artifact)],
            "root": "cc_booking",
        },
    )
    assert inserted.status_code == 200, inserted.text
    version = inserted.json()["document"]["current_version"]

    branch = page_containers(document["scene"])[1]
    rejected = apply(
        client,
        document["id"],
        version,
        {
            "kind": "move_node",
            "page_id": page["id"],
            "id": branch,
            "new_parent": "cc_booking",
            "index": 0,
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "web_operations.invalid"

    repository = HybridRepository()
    # D2.4B: the registry lives on Postgres; purge the row there to simulate the
    # missing-artifact case the renderer must contain. The citing compilation rows go
    # first: their artifact FK is ON DELETE SET NULL, and that SET NULL is itself an
    # UPDATE, which the compilation table's immutability trigger rejects. (No production
    # path deletes an artifact — the registry is INSERT-only — and the account CASCADE
    # removes compilations outright, so this ordering is a test-only concern.)
    for statement in (
        "DELETE FROM design_custom_component_compilation"
        " WHERE artifact_id = :i AND workspace_id = :w",
        "DELETE FROM design_custom_component_artifact"
        " WHERE artifact_id = :i AND workspace_id = :w",
    ):
        repository._bridge._run(
            lambda conn, sql=statement: conn.execute(
                sa_text(sql),
                {"i": artifact["artifact_id"], "w": repository.workspace_id},
            )
        )

    rendered = client.get(f"/documents/{document['id']}/web/render")
    assert rendered.status_code == 200, rendered.text
    assert "Custom component unavailable" in rendered.json()["html"]

    unrelated_resize = apply(
        client,
        document["id"],
        version,
        {
            "kind": "set_node_classes",
            "page_id": page["id"],
            "id": "cc_booking",
            "classes": "w-[600px] h-[320px]",
        },
    )
    assert unrelated_resize.status_code == 200, unrelated_resize.text

    after_resize = get_document(client, document["id"])
    duplicate = copy.deepcopy(
        after_resize["scene"]["pages"][0]["nodes"]["cc_booking"]
    )
    duplicate["id"] = "cc_missing_copy"
    blocked_duplicate = apply(
        client,
        document["id"],
        after_resize["current_version"],
        {
            "kind": "insert_node",
            "page_id": page["id"],
            "parent": parent,
            "index": 1,
            "nodes": [duplicate],
            "root": duplicate["id"],
        },
    )
    assert blocked_duplicate.status_code == 422
    assert (
        blocked_duplicate.json()["detail"]["code"]
        == "custom_component.artifact_unresolved"
    )


# D2.5B DELETED `test_migration_is_deterministic_and_does_not_invent_registry_rows`: it applied
# the SQLite migrations twice and counted rows in the `custom_components` /
# `custom_component_artifacts` SQLite tables. Both the migrations and those tables are deleted.
