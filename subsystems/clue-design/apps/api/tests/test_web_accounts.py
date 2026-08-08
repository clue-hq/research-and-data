"""Website-mode personalization accounts (P5 D3) + the account_values projection.

Accounts CRUD runs over the real API + temp DB via the shared `client` fixture;
account_values is exercised directly against a Repository so its value-namespace
mapping and logo asset-record projection are pinned without a derive call.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_client

from lumen_api.database import Repository, connect
from lumen_api.design_store import HybridRepository
from lumen_api.main import account_values, create_app


# Smallest valid PNG (1x1) — a real logo asset for the resolution/records paths.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "api.sqlite3")
    return make_client(app)


def upload_logo(client: TestClient, label: str = "Acme logo") -> str:
    response = client.post(
        "/assets",
        files={"file": ("logo.png", TINY_PNG, "image/png")},
        data={"label": label, "kind": "raster_image"},
    )
    assert response.status_code == 200, response.text
    return response.json()["asset"]["id"]


# --- CRUD -------------------------------------------------------------------


def test_create_account_mints_id_and_persists(client: TestClient) -> None:
    response = client.post(
        "/web/accounts",
        json={"name": "Privia Health", "domain": "priviahealth.com"},
    )
    assert response.status_code == 200, response.text
    account = response.json()
    assert account["account_id"].startswith("acc_")
    assert account["name"] == "Privia Health"
    assert account["domain"] == "priviahealth.com"
    assert account["data"] == {}
    assert account["logo_asset_id"] is None

    # It reads back.
    got = client.get(f"/web/accounts/{account['account_id']}")
    assert got.status_code == 200
    assert got.json()["account_id"] == account["account_id"]


def test_create_account_with_explicit_id_and_duplicate_409(client: TestClient) -> None:
    first = client.post(
        "/web/accounts", json={"account_id": "acc_explicit", "name": "One"}
    )
    assert first.status_code == 200, first.text
    dup = client.post(
        "/web/accounts", json={"account_id": "acc_explicit", "name": "Two"}
    )
    assert dup.status_code == 409, dup.text
    assert dup.json()["detail"]["code"] == "web_account.exists"


def test_create_account_unresolvable_logo_422(client: TestClient) -> None:
    response = client.post(
        "/web/accounts",
        json={"name": "No logo co", "logo_asset_id": "asset_missing"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "web_account.logo_unresolved"


def test_create_account_with_valid_logo(client: TestClient) -> None:
    logo_id = upload_logo(client)
    response = client.post(
        "/web/accounts",
        json={"name": "Logo co", "logo_asset_id": logo_id, "data": {"tier": "gold"}},
    )
    assert response.status_code == 200, response.text
    account = response.json()
    assert account["logo_asset_id"] == logo_id
    assert account["data"] == {"tier": "gold"}


def test_list_accounts_is_name_sorted(client: TestClient) -> None:
    for name in ("Zeta", "alpha", "Mango"):
        assert client.post("/web/accounts", json={"name": name}).status_code == 200
    names = [a["name"] for a in client.get("/web/accounts").json()["accounts"]]
    assert names == ["alpha", "Mango", "Zeta"]


def test_get_unknown_account_404(client: TestClient) -> None:
    response = client.get("/web/accounts/acc_nope")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "web_account.not_found"


def test_patch_account_partial_update(client: TestClient) -> None:
    account_id = client.post(
        "/web/accounts",
        json={"name": "Before", "domain": "before.com", "data": {"a": "1"}},
    ).json()["account_id"]

    # Only name + data are sent; domain is untouched, data replaces wholesale.
    response = client.patch(
        f"/web/accounts/{account_id}",
        json={"name": "After", "data": {"b": "2"}},
    )
    assert response.status_code == 200, response.text
    account = response.json()
    assert account["name"] == "After"
    assert account["domain"] == "before.com"
    assert account["data"] == {"b": "2"}


def test_patch_account_validates_logo(client: TestClient) -> None:
    account_id = client.post("/web/accounts", json={"name": "X"}).json()["account_id"]
    response = client.patch(
        f"/web/accounts/{account_id}", json={"logo_asset_id": "asset_missing"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "web_account.logo_unresolved"


def test_patch_unknown_account_404(client: TestClient) -> None:
    response = client.patch("/web/accounts/acc_nope", json={"name": "x"})
    assert response.status_code == 404


def test_delete_account(client: TestClient) -> None:
    account_id = client.post("/web/accounts", json={"name": "Gone"}).json()[
        "account_id"
    ]
    response = client.delete(f"/web/accounts/{account_id}")
    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    assert client.get(f"/web/accounts/{account_id}").status_code == 404


def test_delete_unknown_account_404(client: TestClient) -> None:
    assert client.delete("/web/accounts/acc_nope").status_code == 404


# --- account_values projection (D1) -----------------------------------------


def test_account_values_maps_namespace_and_logo_record(client: TestClient) -> None:
    logo_id = upload_logo(client, label="Brand mark")
    account = {
        "account_id": "acc_v",
        "name": "Privia Health",
        "domain": "priviahealth.com",
        "logo_asset_id": logo_id,
        "data": {"headline": "Care that connects", "cta": "Book a demo"},
        "notes": "agent-only context — never substituted",
    }
    repo = HybridRepository(connect(client.app.state.database_path))
    try:
        values, asset_records = account_values(account, repo)
    finally:
        repo.connection.close()

    assert values["account.name"] == {"kind": "text", "value": "Privia Health"}
    assert values["account.domain"] == {"kind": "text", "value": "priviahealth.com"}
    assert values["account.logo"] == {
        "kind": "asset",
        "asset_id": logo_id,
        "alt": "Privia Health logo",
    }
    assert values["account.headline"] == {
        "kind": "text",
        "value": "Care that connects",
    }
    assert values["account.cta"] == {"kind": "text", "value": "Book a demo"}
    # notes are agent context, never a value.
    assert not any(k.endswith("notes") for k in values)
    # The logo's engine AssetRecord is projected for the derive call.
    assert len(asset_records) == 1
    assert asset_records[0]["id"] == logo_id


def test_account_values_without_domain_or_logo(client: TestClient) -> None:
    account = {
        "account_id": "acc_bare",
        "name": "Bare Co",
        "domain": None,
        "logo_asset_id": None,
        "data": {},
        "notes": None,
    }
    repo = HybridRepository(connect(client.app.state.database_path))
    try:
        values, asset_records = account_values(account, repo)
    finally:
        repo.connection.close()
    assert values == {"account.name": {"kind": "text", "value": "Bare Co"}}
    assert asset_records == []


def test_account_values_logo_row_missing_yields_no_record(client: TestClient) -> None:
    # A DELETE keeps the account_id/logo string but the asset row may be gone:
    # the value still points at it (unbound at derive), no record projected.
    account = {
        "account_id": "acc_ghost",
        "name": "Ghost",
        "domain": None,
        "logo_asset_id": "asset_deleted",
        "data": {},
        "notes": None,
    }
    repo = HybridRepository(connect(client.app.state.database_path))
    try:
        values, asset_records = account_values(account, repo)
    finally:
        repo.connection.close()
    assert values["account.logo"] == {
        "kind": "asset",
        "asset_id": "asset_deleted",
        "alt": "Ghost logo",
    }
    assert asset_records == []
