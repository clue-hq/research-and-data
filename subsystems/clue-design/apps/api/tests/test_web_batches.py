"""Website-mode personalization batches (P5 D5 + editor-wave amendment):
POST /documents/{id}/web/batch, POST /web/batches/{id}/resume, GET /web/batches/{id}.

Drives the real core helper + the real node Tailwind toolchain (publish) end to
end against a temp DB. The response echoes `cursor` + `status` top-level; status
is "completed" when done, "partial" when interrupted (the editor's Resume seam),
"failed" only when the batch itself cannot run. Per-account failures are isolated
on their manifest row and never kill the batch.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import is_served, make_client

from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app, new_id


MARKER_HTML = """
<section id="hero">
  <h1 id="head">Meet <span data-var="account.name">Acme Health</span></h1>
  <p id="tag" data-slot="account.tagline">A better way to work</p>
</section>
"""


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "engine-cache")
    return make_client(app)


def create_web_document(client: TestClient, title: str = "Acme Site") -> dict:
    response = client.post("/documents", json={"doc_kind": "web", "title": title})
    assert response.status_code == 200, response.text
    return response.json()["document"]


def seed_template(client: TestClient, document_id: str) -> None:
    web_doc = client.get(f"/documents/{document_id}").json()["scene"]
    response = client.app.state.core.web_ingest_html(
        web_doc, "home", MARKER_HTML, None, None
    )
    errors = [d for d in response.get("diagnostics", []) if d.get("severity") == "error"]
    assert not errors, response.get("diagnostics")
    store = HybridRepository()
    store.update_web_document(
        document_id,
        response["web_doc"],
        intent="seed",
        checkpoint_label="seed",
        operations=[{"kind": "replace_web_doc"}],
        inverse_operations=None,
    )


def make_account(client: TestClient, name: str, tagline: str = "Better care") -> str:
    return client.post(
        "/web/accounts", json={"name": name, "data": {"tagline": tagline}}
    ).json()["account_id"]


# --- happy path -------------------------------------------------------------


def test_batch_publishes_all_accounts(client: TestClient, workspace_id: str) -> None:
    document = create_web_document(client)
    seed_template(client, document["id"])
    accounts = [
        make_account(client, "Privia Health"),
        make_account(client, "Beta Care"),
        make_account(client, "Gamma Clinics"),
    ]

    response = client.post(
        f"/documents/{document['id']}/web/batch",
        json={"account_ids": accounts, "publish": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["cursor"] == 3
    assert body["counts"] == {"total": 3, "derived": 0, "published": 3, "failed": 0}

    manifest = body["manifest"]
    assert len(manifest) == 3
    slugs = set()
    for row in manifest:
        assert row["status"] == "published"
        assert row["document_id"]
        assert row["url"].endswith(f"/{row['slug']}")
        assert row["error"] is None
        slugs.add(row["slug"])
        # Each published page is really live at its slug. (The design API no longer SERVES
        # published pages — the page origin does, and `row["url"]` is that origin's absolute
        # URL — so liveness is read off the publish row.)
        assert is_served(workspace_id, row["slug"]), row["url"]
    assert len(slugs) == 3  # distinct slugs


def test_batch_derive_only_when_publish_false(client: TestClient) -> None:
    document = create_web_document(client)
    seed_template(client, document["id"])
    accounts = [make_account(client, "Solo Co")]
    body = client.post(
        f"/documents/{document['id']}/web/batch",
        json={"account_ids": accounts, "publish": False},
    ).json()
    assert body["status"] == "completed"
    assert body["counts"] == {"total": 1, "derived": 1, "published": 0, "failed": 0}
    row = body["manifest"][0]
    assert row["status"] == "derived"
    assert row["slug"] is None and row["url"] is None
    assert row["document_id"]


# --- slug collision suffixing -----------------------------------------------


def test_batch_slug_collision_suffixes(client: TestClient) -> None:
    document = create_web_document(client)
    seed_template(client, document["id"])
    # Two DIFFERENT accounts with the SAME name → same base slug → the second is
    # suffixed rather than 409ing.
    accounts = [
        make_account(client, "Acme Health"),
        make_account(client, "Acme Health"),
    ]
    body = client.post(
        f"/documents/{document['id']}/web/batch",
        json={"account_ids": accounts, "publish": True},
    ).json()
    assert body["status"] == "completed"
    assert body["counts"]["published"] == 2
    slugs = [row["slug"] for row in body["manifest"]]
    assert len(set(slugs)) == 2
    assert any(slug.endswith("-2") for slug in slugs), slugs


def test_batch_slug_base_override(client: TestClient) -> None:
    document = create_web_document(client)
    seed_template(client, document["id"])
    account = make_account(client, "Privia Health")
    body = client.post(
        f"/documents/{document['id']}/web/batch",
        json={"account_ids": [account], "publish": True, "slug_base": "abm-fall"},
    ).json()
    slug = body["manifest"][0]["slug"]
    assert slug == "abm-fall-privia-health", slug


# --- per-account failure isolation ------------------------------------------


def test_batch_isolates_per_account_failure(client: TestClient) -> None:
    document = create_web_document(client)
    seed_template(client, document["id"])
    good_one = make_account(client, "Privia Health")
    good_two = make_account(client, "Beta Care")
    # A ghost account id in the middle: its row fails, the others still publish;
    # the batch completes rather than dying.
    accounts = [good_one, "acc_ghost_missing", good_two]

    body = client.post(
        f"/documents/{document['id']}/web/batch",
        json={"account_ids": accounts, "publish": True},
    ).json()
    assert body["status"] == "completed"
    assert body["cursor"] == 3
    assert body["counts"] == {"total": 3, "derived": 0, "published": 2, "failed": 1}

    by_id = {row["account_id"]: row for row in body["manifest"]}
    assert by_id["acc_ghost_missing"]["status"] == "failed"
    assert by_id["acc_ghost_missing"]["error"]
    assert by_id["acc_ghost_missing"]["document_id"] is None
    assert by_id[good_one]["status"] == "published"
    assert by_id[good_two]["status"] == "published"


# --- resume + snapshot ------------------------------------------------------


def test_resume_from_mid_cursor(client: TestClient) -> None:
    document = create_web_document(client)
    seed_template(client, document["id"])
    accounts = [
        make_account(client, "Privia Health"),
        make_account(client, "Beta Care"),
        make_account(client, "Gamma Clinics"),
    ]
    # Construct a batch left "partial" after its first account (cursor=1), as if
    # the process had been interrupted mid-run.
    store = HybridRepository()
    batch = store.create_web_batch(
        {
            "batch_id": new_id("wbatch"),
            "template_document_id": document["id"],
            "template_doc_version": document["current_version"],
            "status": "partial",
            "account_ids": accounts,
            "publish": True,
            "slug_base": "acme-site",
            "cursor": 1,
            "manifest": [
                {
                    "account_id": accounts[0],
                    "account_name": "Privia Health",
                    "document_id": "doc_seeded",
                    "slug": "acme-site-privia-health",
                    "url": "/p/acme-site-privia-health",
                    "status": "published",
                    "unbound": [],
                    "error": None,
                }
            ],
        }
    )
    batch_id = batch["batch_id"]

    # Before resume: the snapshot reports partial with cursor < total.
    snapshot = client.get(f"/web/batches/{batch_id}").json()
    assert snapshot["status"] == "partial"
    assert snapshot["cursor"] == 1 < snapshot["counts"]["total"]

    resumed = client.post(f"/web/batches/{batch_id}/resume").json()
    assert resumed["status"] == "completed"
    assert resumed["cursor"] == 3
    assert len(resumed["manifest"]) == 3
    assert resumed["counts"]["published"] == 3  # 1 pre-seeded + 2 new

    # Resuming a completed batch is a no-op that returns the same snapshot.
    again = client.post(f"/web/batches/{batch_id}/resume").json()
    assert again["status"] == "completed"
    assert again["cursor"] == 3


def test_get_snapshot_matches(client: TestClient) -> None:
    document = create_web_document(client)
    seed_template(client, document["id"])
    account = make_account(client, "Privia Health")
    posted = client.post(
        f"/documents/{document['id']}/web/batch",
        json={"account_ids": [account], "publish": False},
    ).json()

    got = client.get(f"/web/batches/{posted['batch_id']}")
    assert got.status_code == 200
    snapshot = got.json()
    assert snapshot["batch_id"] == posted["batch_id"]
    assert snapshot["status"] == posted["status"]
    assert snapshot["cursor"] == posted["cursor"]
    assert snapshot["counts"] == posted["counts"]
    assert snapshot["manifest"] == posted["manifest"]


def test_get_snapshot_unknown_batch_404(client: TestClient) -> None:
    response = client.get("/web/batches/wbatch_missing")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "web_batch.not_found"
