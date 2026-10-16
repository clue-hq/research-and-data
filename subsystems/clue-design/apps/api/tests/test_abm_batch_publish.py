"""ABM batch personalization + publish (clone-fidelity F4.3, rulings R25-1…R25-7).

F4.2 made the ABM page a TEMPLATE: one document whose slots hold `{{account.name}}` /
`{{account.logo}}` / `{{account.domain}}`. This is the run that turns it into N published pages,
and the four things it had to grow to do that honestly:

* **The G1+G2 bridge** (R25-1). `DurableAgentAccountLogoBinder` puts a ladder-fetched mark into
  the `design_asset` registry (G1) and stamps `design_account.logo_asset_id` (G2), so
  `account_values()` — which reads exactly that one column — finally resolves
  `{{account.logo}}`. Workspace-scoped and fail-closed at every door; an account we hold no mark
  for derives the empty-logo page, which is CORRECT and permanent.
* **`abm-<account>` slugs** (R25-3 / D-F5), deterministic and collision-suffixed.
* **`noindex` as a per-page publish OPTION** (R25-4). The account page carries the robots meta;
  an ordinary homepage publish is byte-identical to what it was before this task. Both
  directions pinned, because a global flip would quietly de-index every client homepage we host.
* **The template never publishes** (R25-7). An un-derived ABM page renders literal `{{…}}` to a
  visitor, so the publish seam refuses it by name. The batch path is structurally safe already —
  it publishes what it derived — and that is pinned too rather than assumed.

DB-backed, with the suite's per-test workspace + disposable `FsStorage`. The agent half of the
bridge — the tool, its refusals — is `apps/agent_runtime/tests/test_web_account_logo_bind.py`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from clue_storage import FsStorage
from fastapi.testclient import TestClient

from conftest import is_served, make_client, published_html

from lumen_api.design_store import DesignBlobStore, HybridRepository
from lumen_api.fragments.campaign_shell import CAMPAIGN_SHELL_FOOTER, CAMPAIGN_SHELL_HEADER
from lumen_api.main import create_app
from lumen_api.public_pages import site_address

from test_abm_assembly import (  # the F4.2 template, reused rather than re-built
    TINY_PNG,
    _assembled_doc,
    _registry,
    _released_hero,
    _released_shell,
)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def client(tmp_path: Path, design_storage: FsStorage) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def _abm_template(
    client: TestClient,
    workspace_id: str,
    storage: FsStorage,
    cache: Path,
    document_id: str = "doc_abm_template",
) -> str:
    registry = _registry(workspace_id, storage, cache)
    registry.campaign_shell_placeholder()
    header = _released_shell(registry, CAMPAIGN_SHELL_HEADER)
    footer = _released_shell(registry, CAMPAIGN_SHELL_FOOTER)
    hero = _released_hero(workspace_id, storage)
    HybridRepository(workspace_id=workspace_id).create_document(
        _assembled_doc(document_id, header, hero, footer), doc_kind="web"
    )
    return document_id


def _account(client: TestClient, name: str, *, logo_asset_id: str | None = None) -> str:
    body = {"name": name, "domain": f"{name.split()[0].lower()}.example"}
    if logo_asset_id:
        body["logo_asset_id"] = logo_asset_id
    response = client.post("/web/accounts", json=body)
    assert response.status_code == 200, response.text
    return response.json()["account_id"]


def _upload_logo(client: TestClient, label: str) -> str:
    return client.post(
        "/assets",
        files={"file": ("mark.png", TINY_PNG, "image/png")},
        data={"label": label, "kind": "raster_image"},
    ).json()["asset"]["id"]


# --------------------------------------------------------------------------- #
# R25-3 — the slug rule, stated exactly and pinned
# --------------------------------------------------------------------------- #


def test_the_abm_slug_rule_is_the_prefix_plus_the_slugified_account_name() -> None:
    """D-F5, spelled out: `abm-` + the display name lowercased, non-alnum runs collapsed to one
    dash, dashes trimmed. Nothing about the template's title enters an ABM slug."""
    from lumen_api.main import ABM_SLUG_BASE, abm_account_slug

    assert ABM_SLUG_BASE == "abm"
    assert abm_account_slug("Goodman Campbell Brain & Spine") == (
        "abm-goodman-campbell-brain-spine"
    )
    assert abm_account_slug("Privia Health") == "abm-privia-health"
    assert abm_account_slug("  ACME   Health, Inc.  ") == "abm-acme-health-inc"
    # An unslugifiable name still yields a legal slug rather than a crash.
    assert abm_account_slug("...") == "abm-site"


def test_two_accounts_with_one_name_take_suffixed_slugs_not_one_page(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    accounts = [_account(client, "Acme Health"), _account(client, "Acme Health")]

    body = client.post(
        f"/documents/{template}/web/batch",
        json={"account_ids": accounts, "publish": True, "abm": True},
    ).json()

    slugs = [row["slug"] for row in body["manifest"]]
    assert slugs == ["abm-acme-health", "abm-acme-health-2"]


def test_an_abm_batch_refuses_a_caller_supplied_slug_base_rather_than_overriding_it(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")

    response = client.post(
        f"/documents/{template}/web/batch",
        json={
            "account_ids": [_account(client, "Acme Health")],
            "publish": True,
            "abm": True,
            "slug_base": "spring-campaign",
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "web_batch.slug_base_conflict"


# --------------------------------------------------------------------------- #
# R25-2 / R25-5 — the batch walk and what its manifest says
# --------------------------------------------------------------------------- #


def test_the_batch_derives_and_publishes_one_page_per_account_and_says_which_carried_a_logo(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """Red case 3. A mixed run — one account with a bound logo, one without — is N documents at
    `abm-<account>` slugs, every one publishable, and the manifest reads afterwards."""
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    logo = _upload_logo(client, "Goodman Campbell logo")
    with_logo = _account(client, "Goodman Campbell", logo_asset_id=logo)
    without_logo = _account(client, "Privia Health")

    body = client.post(
        f"/documents/{template}/web/batch",
        json={"account_ids": [with_logo, without_logo], "publish": True, "abm": True},
    ).json()

    assert body["status"] == "completed"
    rows = {row["account_id"]: row for row in body["manifest"]}
    assert set(rows) == {with_logo, without_logo}
    for row in rows.values():
        assert row["status"] == "published"
        assert row["document_id"]
        assert row["slug"].startswith("abm-")
        assert row["url"].endswith(f"/{row['slug']}")
        assert row["noindex"] is True
        assert row["error"] is None
        assert is_served(workspace_id, row["slug"])
    # R25-2: the manifest SAYS, per account, whether a logo was bound or the slot derived empty.
    assert rows[with_logo]["logo"] == {"bound": True, "asset_id": logo}
    assert rows[without_logo]["logo"] == {"bound": False, "reason": "no_logo_on_account"}
    # R25-5: readable after the fact, not only in the call's response.
    later = client.get(f"/web/batches/{body['batch_id']}").json()
    assert later["manifest"] == body["manifest"]


def test_the_batch_fires_no_logo_fetch_of_its_own(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """Ruling R25-2: populating logos is an EXPLICIT prior per-account act, never a fan-out the
    batch route starts. An account with no bound logo derives the empty-logo page and the run
    reaches out to nobody."""
    import lumen_agent.tools.logo_fetch as logo_fetch

    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    calls: list = []

    original = logo_fetch.fetch_logo_family
    logo_fetch.fetch_logo_family = lambda *a, **k: calls.append(a) or original(*a, **k)
    try:
        body = client.post(
            f"/documents/{template}/web/batch",
            json={"account_ids": [_account(client, "Privia Health")], "publish": True, "abm": True},
        ).json()
    finally:
        logo_fetch.fetch_logo_family = original

    assert calls == []
    assert body["manifest"][0]["logo"] == {"bound": False, "reason": "no_logo_on_account"}


def test_a_bound_logo_reaches_the_published_account_page(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    logo = _upload_logo(client, "Goodman Campbell logo")
    account = _account(client, "Goodman Campbell", logo_asset_id=logo)
    digest = HybridRepository(workspace_id=workspace_id).require_asset_record(logo)["asset"][
        "media"
    ]["digest"]["value"]

    body = client.post(
        f"/documents/{template}/web/batch",
        json={"account_ids": [account], "publish": True, "abm": True},
    ).json()

    page = published_html(workspace_id, body["manifest"][0]["slug"])
    assert f"/asset-store/{digest}" in page
    assert "Goodman Campbell" in page


def test_re_running_an_abm_batch_converges_on_one_document_per_account(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """Red case 8. Fifty accounts re-derived after a template edit must be fifty pages, not a
    hundred — and the slug must stay the slug somebody already sent out."""
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    account = _account(client, "Goodman Campbell")

    first = client.post(
        f"/documents/{template}/web/batch",
        json={"account_ids": [account], "publish": True, "abm": True},
    ).json()["manifest"][0]
    second = client.post(
        f"/documents/{template}/web/batch",
        json={"account_ids": [account], "publish": True, "abm": True},
    ).json()["manifest"][0]

    assert second["document_id"] == first["document_id"]
    assert second["slug"] == first["slug"] == "abm-goodman-campbell"
    assert second["status"] == "published"
    # The id is the (template, account) pair's own, and the second run gained a REVISION on it
    # rather than a twin document beside it.
    from lumen_api.main import abm_derived_document_id

    assert first["document_id"] == abm_derived_document_id(template, account)
    document = HybridRepository(workspace_id=workspace_id).require_document(
        first["document_id"]
    )
    assert document["current_version"] > 0
    assert document["account_id"] == account


# --------------------------------------------------------------------------- #
# R25-4 — noindex is an OPTION, and both directions are pinned
# --------------------------------------------------------------------------- #

ROBOTS_META = '<meta name="robots" content="noindex">'


def test_the_account_page_carries_the_robots_meta(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    body = client.post(
        f"/documents/{template}/web/batch",
        json={"account_ids": [_account(client, "Acme Health")], "publish": True, "abm": True},
    ).json()

    page = published_html(workspace_id, body["manifest"][0]["slug"])
    assert ROBOTS_META in page


def test_an_ordinary_publish_is_byte_identical_to_what_it_was_before_this_task(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """The other direction: an INDEXABLE page's publish must not quietly become noindex, and the
    ONLY difference the option makes is the one meta line. (Founder ruling 2026-10-16: a new
    page is born noindex, so the page here is made indexable by the explicit "Allow indexing"
    clear first — what a person does in Share.)"""
    from lumen_api import web_export

    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    published = client.post(
        f"/documents/{template}/web/publish", json={"slug": "insight-home"}
    )
    # Founder ruling 2026-08-29: the template PUBLISHES (warn-loud, never refused). This
    # test's subject is the derived page's byte-identity, so continue with the derived one.
    assert published.status_code == 200
    account = _account(client, "Acme Health")
    derived = client.post(
        f"/documents/{template}/web/derive", json={"account_id": account}
    ).json()["document_id"]
    allowed = client.put(f"/documents/{derived}/web-noindex", json={"noindex": False})
    assert allowed.status_code == 200, allowed.text
    ordinary = client.post(f"/documents/{derived}/web/publish", json={"slug": "acme-home"})
    assert ordinary.status_code == 200, ordinary.text

    page = published_html(workspace_id, "acme-home")
    assert "robots" not in page
    row = HybridRepository(workspace_id=workspace_id).get_web_publish("acme-home")
    assert "robots" not in (row.get("manifest") or {})

    # And the option's whole effect is additive: same package, one extra meta line.
    app = client.app
    document = HybridRepository(workspace_id=workspace_id).require_document(derived)
    blobs = DesignBlobStore(design_storage, workspace_id)
    kwargs = dict(
        blobs=blobs,
        slug="acme-home",
        site_address=site_address(HybridRepository(workspace_id=workspace_id), "acme-home"),
        workspace_id=workspace_id,
        node_bin=app.state.web_export_node_bin,
    )
    plain = web_export.build_publish_package(
        app.state.core, HybridRepository(workspace_id=workspace_id), document, **kwargs
    )
    hidden = web_export.build_publish_package(
        app.state.core,
        HybridRepository(workspace_id=workspace_id),
        document,
        noindex=True,
        **kwargs,
    )
    assert ROBOTS_META not in plain.html
    assert "noindex" not in plain.html
    assert "robots" not in plain.manifest
    assert ROBOTS_META in hidden.html
    assert hidden.manifest["robots"] == "noindex"
    # The option's effect is BOUNDED: one meta line, plus the manifest digest that line's
    # manifest entry moves (which is what a content-addressed manifest is for). Nothing else.
    normalized = hidden.html.replace(ROBOTS_META + "\n", "").replace(
        hidden.manifest_digest, plain.manifest_digest
    )
    assert normalized == plain.html


# --------------------------------------------------------------------------- #
# R-F1 — noindex is DURABLE on the document, applied by every publish route
# --------------------------------------------------------------------------- #
#
# FOUNDER RULING R-F1 (2026-08-29) supersedes R25-4's publish-time-argument shape above: the
# flag is stored permanently on the page and applied on EVERY republish, whichever route
# publishes it, and only an EXPLICIT named action clears it. The R25-4 tests above are kept
# rather than rewritten — the option still exists and still behaves exactly as they pin it;
# what these add is the half that outlives one request body.


def test_the_batch_stamps_the_durable_flag_on_every_abm_page_it_publishes(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """R-F1's first writer. The batch's always-ask became the stamp: the DOCUMENT carries it."""
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    body = client.post(
        f"/documents/{template}/web/batch",
        json={"account_ids": [_account(client, "Acme Health")], "publish": True, "abm": True},
    ).json()

    repo = HybridRepository(workspace_id=workspace_id)
    document = repo.require_document(body["manifest"][0]["document_id"])
    assert document["web_noindex"] is True
    # The template it was derived from carries the flag only because every new web document is
    # born with it (founder ruling 2026-10-16); the batch writes nothing onto the template.
    assert repo.require_document(template)["web_noindex"] is True


def test_a_plain_republish_of_an_abm_page_keeps_the_robots_meta(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """THE red case R-F1 exists for. `POST /documents/{id}/web/publish` carries no `noindex`
    field at all, and before this ruling that re-published the account page INDEXED."""
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    body = client.post(
        f"/documents/{template}/web/batch",
        json={"account_ids": [_account(client, "Acme Health")], "publish": True, "abm": True},
    ).json()
    row = body["manifest"][0]
    assert ROBOTS_META in published_html(workspace_id, row["slug"])

    republished = client.post(
        f"/documents/{row['document_id']}/web/publish", json={"slug": row["slug"]}
    )

    assert republished.status_code == 200, republished.text
    assert ROBOTS_META in published_html(workspace_id, row["slug"])
    publish = HybridRepository(workspace_id=workspace_id).get_web_publish(row["slug"])
    assert publish["manifest"]["robots"] == "noindex"


def test_the_toolbelt_publish_tool_honors_the_durable_flag_without_being_asked(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """Every publish path, not only the HTTP one: the OR lives at the single publish write."""
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    account = _account(client, "Acme Health")
    derived = client.post(
        f"/documents/{template}/web/derive", json={"account_id": account}
    ).json()["document_id"]
    stamped = client.put(f"/documents/{derived}/web-noindex", json={"noindex": True})
    assert stamped.status_code == 200, stamped.text

    client.app.state.design_tools.invoke(
        "design_publish_web",
        {
            "document_id": derived,
            "slug": "tool-published",
        },
        workspace_id=workspace_id,
    )

    assert ROBOTS_META in published_html(workspace_id, "tool-published")


def test_clearing_the_durable_flag_is_an_explicit_named_call_and_a_publish_cannot_do_it(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """Both halves of "removing it requires an explicit action".

    The toggle names the field and the field is REQUIRED, so a body that merely omits it is a
    422 rather than a silent clear — which is the same guarantee the publish routes give by
    never carrying the field at all.
    """
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    body = client.post(
        f"/documents/{template}/web/batch",
        json={"account_ids": [_account(client, "Acme Health")], "publish": True, "abm": True},
    ).json()
    row = body["manifest"][0]

    # A toggle call that names no value clears nothing.
    assert client.put(f"/documents/{row['document_id']}/web-noindex", json={}).status_code == 422
    repo = HybridRepository(workspace_id=workspace_id)
    assert repo.require_document(row["document_id"])["web_noindex"] is True

    cleared = client.put(
        f"/documents/{row['document_id']}/web-noindex", json={"noindex": False}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["web_noindex"] is False
    assert repo.require_document(row["document_id"])["web_noindex"] is False

    republished = client.post(
        f"/documents/{row['document_id']}/web/publish", json={"slug": row["slug"]}
    )
    assert republished.status_code == 200, republished.text
    assert ROBOTS_META not in published_html(workspace_id, row["slug"])


def test_a_derived_document_is_born_stamped_and_only_allow_indexing_unstamps_it(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """Founder ruling 2026-10-16 (it replaced "an ordinary document is born un-stamped"): every
    new website document is born with the durable flag, a derived page from the single-account
    derive route included, so its plain publish serves the robots meta. Ticking "Allow
    indexing" (the explicit clear) is enough to make the next publish indexable."""
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    account = _account(client, "Acme Health")
    derived = client.post(
        f"/documents/{template}/web/derive", json={"account_id": account}
    ).json()["document_id"]
    generic = client.post(f"/documents/{template}/web/derive", json={}).json()["document_id"]
    repo = HybridRepository(workspace_id=workspace_id)
    assert repo.require_document(derived)["web_noindex"] is True
    assert repo.require_document(generic)["web_noindex"] is True

    assert (
        client.post(f"/documents/{derived}/web/publish", json={"slug": "plain-home"}).status_code
        == 200
    )
    assert ROBOTS_META in published_html(workspace_id, "plain-home")
    assert repo.get_web_publish("plain-home")["manifest"]["robots"] == "noindex"

    assert (
        client.put(f"/documents/{derived}/web-noindex", json={"noindex": False}).status_code
        == 200
    )
    assert (
        client.post(f"/documents/{derived}/web/publish", json={"slug": "plain-home"}).status_code
        == 200
    )
    page = published_html(workspace_id, "plain-home")
    assert "robots" not in page
    assert "robots" not in (repo.get_web_publish("plain-home").get("manifest") or {})


def test_the_toggle_refuses_a_scene_document(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """A scene has no publish surface, so the flag would be a lie stored on it."""
    scene = client.post("/documents", json={}).json()["document"]["id"]

    response = client.put(f"/documents/{scene}/web-noindex", json={"noindex": True})

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "document.kind_unsupported"


# --------------------------------------------------------------------------- #
# R25-7 — the template never publishes
# --------------------------------------------------------------------------- #


def test_publishing_the_un_derived_template_publishes_and_warns(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """FOUNDER RULING 2026-08-29 (supersedes the R25-7 refusal, which the founder never
    ordered): NO mechanical gate blocks the design path. An un-derived template PUBLISHES;
    the manifest warns loudly about the markers it still shows; deriving remains the way to
    personalize them."""
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")

    response = client.post(
        f"/documents/{template}/web/publish", json={"slug": "abm-template"}
    )

    assert response.status_code == 200, response.text
    published = HybridRepository(workspace_id=workspace_id).get_web_publish("abm-template")
    assert published is not None
    manifest = published.get("manifest") or {}
    joined = str(manifest)
    assert "unsubstituted account markers" in joined
    assert "{{account.name}}" in joined


def test_the_derived_page_publishes_because_it_has_no_markers_left(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    account = _account(client, "Acme Health")
    derived = client.post(
        f"/documents/{template}/web/derive", json={"account_id": account}
    ).json()["document_id"]

    response = client.post(f"/documents/{derived}/web/publish", json={"slug": "abm-acme"})

    assert response.status_code == 200, response.text
    page = published_html(workspace_id, "abm-acme")
    assert "{{account." not in page


def test_the_batch_publishes_only_what_it_derived(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """Structural half of R25-7: every slug the batch mints points at a DERIVED document, never
    at the template it read."""
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    accounts = [_account(client, "Acme Health"), _account(client, "Privia Health")]

    body = client.post(
        f"/documents/{template}/web/batch",
        json={"account_ids": accounts, "publish": True, "abm": True},
    ).json()

    repo = HybridRepository(workspace_id=workspace_id)
    for row in body["manifest"]:
        assert row["document_id"] != template
        publish = repo.get_web_publish(row["slug"])
        assert publish["document_id"] == row["document_id"]
        assert repo.require_document(row["document_id"])["account_id"] == row["account_id"]


def test_the_marker_guard_is_the_account_namespace_and_nothing_wider() -> None:
    """A cloned site's own markup can legitimately carry `{{ }}` (a template engine's braces left
    in static HTML). The guard reads OUR grammar — `{{account.…}}` — and nothing else."""
    from lumen_api.fragments.abm_page import unresolved_account_markers

    assert unresolved_account_markers("<p>{{account.name}}</p>") == ("{{account.name}}",)
    assert unresolved_account_markers("<p>{{ account.beds }}</p>") == ("{{ account.beds }}",)
    assert unresolved_account_markers("<p>{{ price | currency }}</p>") == ()
    assert unresolved_account_markers("<p>{{campaign.headline}}</p>") == ()
    assert unresolved_account_markers("<p>Acme Health</p>") == ()


# --------------------------------------------------------------------------- #
# R25-1 — the G1+G2 bridge, on the real binder
# --------------------------------------------------------------------------- #


def _fetched_record(body: bytes, asset_id: str = "asset_ing_deadbeefdeadbeef") -> dict:
    digest = hashlib.sha256(body).hexdigest()
    return {
        "id": asset_id,
        "label": "Goodman Campbell logo (light)",
        "kind": "raster_image",
        "status": "ready",
        "source": {"kind": "website", "url": "https://goodmancampbell.com/brand/logo.png"},
        "media": {
            "mime_type": "image/png",
            "byte_length": len(body),
            "digest": {"algorithm": "sha256", "value": digest},
            "location": {
                "provider": "local-store",
                "opaque_ref": f"sha256/{digest[:2]}/{digest}",
                "url": None,
            },
        },
        "provenance": {"created_by": "logo_ladder", "source_label": "website"},
        "tags": ["target-account", "logo-ladder"],
    }


def _binder(client: TestClient, workspace_id: str, storage: FsStorage, cache: Path):
    """The REAL binder, on the app's REAL governed invoker — both its writes are tools."""
    from lumen_api.agent_account_logos import DurableAgentAccountLogoBinder

    return DurableAgentAccountLogoBinder(
        blobs=DesignBlobStore(storage, workspace_id),
        cache_dir=cache,
        invocations=client.app.state.design_tools,
    )


def _stage_bytes(cache: Path, body: bytes) -> None:
    from lumen_api.asset_custody import write_cache_blob

    write_cache_blob(cache, hashlib.sha256(body).hexdigest(), body)


def test_the_bridge_registers_the_asset_and_stamps_the_account(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """Red case 1, end to end: bind → `require_asset_record` resolves it → the derive of the F4.2
    template renders that account's real digest on its own page."""
    cache = tmp_path / "cache"
    _stage_bytes(cache, TINY_PNG)
    record = _fetched_record(TINY_PNG)
    template = _abm_template(client, workspace_id, design_storage, cache)
    account = _account(client, "Goodman Campbell")

    result = _binder(client, workspace_id, design_storage, cache).bind(
        account_id=account, record=dict(record)
    )

    assert result["asset_id"] == record["id"]
    repo = HybridRepository(workspace_id=workspace_id)
    # G1: the registry the derive reads resolves it.
    assert repo.require_asset_record(record["id"])["asset"]["id"] == record["id"]
    # G2: the column `account_values()` reads is stamped.
    assert repo.require_web_account(account)["logo_asset_id"] == record["id"]

    derived = client.post(
        f"/documents/{template}/web/derive", json={"account_id": account}
    ).json()["document_id"]
    html = client.get(f"/documents/{derived}/web/render").json()["html"]
    assert f"/asset-store/{record['media']['digest']['value']}" in html


def test_the_bridge_refuses_another_workspaces_account_and_stamps_nothing(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """Red case 6 — the B3 law. The binder's tenant comes from its blob store; a foreign account
    id is as unresolvable as an absent one."""
    from lumen_api.agent_account_logos import AccountLogoRefused

    cache = tmp_path / "cache"
    _stage_bytes(cache, TINY_PNG)
    account = _account(client, "Goodman Campbell")
    stranger = _binder(client, "ws_someone_else", design_storage, cache)

    with pytest.raises(AccountLogoRefused) as raised:
        stranger.bind(account_id=account, record=_fetched_record(TINY_PNG))

    assert raised.value.code == "account_logo.unknown_account"
    assert HybridRepository(workspace_id=workspace_id).require_web_account(account)[
        "logo_asset_id"
    ] is None


def test_the_bridge_refuses_a_record_whose_bytes_nothing_holds(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """An account logo bound to bytes nobody can serve is the white-chip failure with extra
    steps. Nothing is registered and nothing is stamped."""
    from lumen_api.agent_account_logos import AccountLogoRefused

    cache = tmp_path / "cache"  # deliberately NOT staged
    account = _account(client, "Goodman Campbell")

    with pytest.raises(AccountLogoRefused) as raised:
        _binder(client, workspace_id, design_storage, cache).bind(
            account_id=account, record=_fetched_record(TINY_PNG)
        )

    assert raised.value.code == "account_logo.bytes_unavailable"
    repo = HybridRepository(workspace_id=workspace_id)
    assert repo.require_web_account(account)["logo_asset_id"] is None


def test_re_binding_the_same_mark_converges(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    cache = tmp_path / "cache"
    _stage_bytes(cache, TINY_PNG)
    account = _account(client, "Goodman Campbell")
    binder = _binder(client, workspace_id, design_storage, cache)

    first = binder.bind(account_id=account, record=_fetched_record(TINY_PNG))
    second = binder.bind(account_id=account, record=_fetched_record(TINY_PNG))

    assert first["changed"] is True and second["changed"] is False
    assert second["previous_asset_id"] == first["asset_id"]
    assert HybridRepository(workspace_id=workspace_id).require_web_account(account)[
        "logo_asset_id"
    ] == first["asset_id"]


# --------------------------------------------------------------------------- #
# R25-6 — the chosen arm: the registration path never depends on `opaque_ref`
# --------------------------------------------------------------------------- #


def test_a_bound_record_resolves_by_digest_whichever_arm_the_resolver_takes(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """Ruling R25-6, arm (b). `store_resolver.rs:29-32` reads `location.opaque_ref` FIRST when
    the provider is `local-store`, so a record carrying a stale or foreign ref renders a white
    chip. Every record this bridge writes is immune, and this is why:

    * the engine's `ingest_asset` sets `opaque_ref = digest_relative_path(digest)` — the SAME
      path the digest fallback computes, so the two arms agree by construction;
    * the bind's custody step then re-points `location` at platform storage
      (`provider: "clue-storage"`), which is not `local-store` at all, so the resolver takes the
      digest arm outright.

    The residual — a hand-authored `local-store` record whose ref names other bytes — cannot be
    produced by this path and is ledgered for the CP2 walk rather than fixed in Rust.
    """
    from clue_design.storage import (
        DESIGN_LOCATION_PROVIDER,
        LEGACY_LOCATION_PROVIDERS,
        location_digest,
    )

    cache = tmp_path / "cache"
    _stage_bytes(cache, TINY_PNG)
    account = _account(client, "Goodman Campbell")
    record = _fetched_record(TINY_PNG)
    digest = record["media"]["digest"]["value"]

    # As handed over by `ingest_asset`: the local-store arm already points at the digest path.
    assert record["media"]["location"]["provider"] in LEGACY_LOCATION_PROVIDERS
    assert record["media"]["location"]["opaque_ref"] == f"sha256/{digest[:2]}/{digest}"
    assert location_digest(record["media"]["location"]) == digest

    _binder(client, workspace_id, design_storage, cache).bind(account_id=account, record=record)

    stored = HybridRepository(workspace_id=workspace_id).require_asset_record(record["id"])[
        "asset"
    ]
    location = stored["media"]["location"]
    assert location["provider"] == DESIGN_LOCATION_PROVIDER  # not `local-store`
    assert location_digest(location) == stored["media"]["digest"]["value"] == digest


def test_a_plain_batch_cannot_wander_into_abm_mode_by_name(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """T25 review I-3: `slug_base == "abm"` IS the persisted ABM mode, so a template TITLED
    "ABM" (title-slugged) or a hand-passed `slug_base="abm"` silently switched a plain batch
    into ABM semantics — noindex + in-place convergence nobody asked for. `abm: true` is now
    the ONLY door; both accidental shapes refuse typed."""
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    registry.campaign_shell_placeholder()
    header = _released_shell(registry, CAMPAIGN_SHELL_HEADER)
    footer = _released_shell(registry, CAMPAIGN_SHELL_FOOTER)
    hero = _released_hero(workspace_id, design_storage)
    titled_abm = _assembled_doc("doc_titled_abm", header, hero, footer)
    titled_abm["title"] = "ABM"
    HybridRepository(workspace_id=workspace_id).create_document(titled_abm, doc_kind="web")
    account = _account(client, "Acme Health")

    by_title = client.post(
        "/documents/doc_titled_abm/web/batch",
        json={"account_ids": [account], "publish": False},
    )
    assert by_title.status_code == 422, by_title.text
    assert by_title.json()["detail"]["code"] == "web_batch.slug_base_reserved"

    explicit = client.post(
        "/documents/doc_titled_abm/web/batch",
        json={"account_ids": [account], "publish": False, "slug_base": "abm"},
    )
    assert explicit.status_code == 422, explicit.text
    assert explicit.json()["detail"]["code"] == "web_batch.slug_base_reserved"


def test_a_re_run_is_one_undo_away_never_a_destroyed_edit(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """T25 review I-1, live-reproduced there: the re-derive wrote `inverse_operations: None`,
    so a re-run silently destroyed any manual edit to a derived page AND sealed its undo stack
    (409 not_invertible). The inverse now carries the prior document, so a re-run is one undo
    away — the shape the undo path already replays."""
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    account = _account(client, "Acme Health")
    first = client.post(
        f"/documents/{template}/web/batch",
        json={"account_ids": [account], "publish": False, "abm": True},
    ).json()
    doc_id = first["manifest"][0]["document_id"]
    repo = HybridRepository(workspace_id=workspace_id)
    scene_before = repo.require_document(doc_id)["scene"]
    assert "Acme Health" in str(scene_before)

    renamed = client.patch(f"/web/accounts/{account}", json={"name": "Acme Health Group"})
    assert renamed.status_code == 200, renamed.text
    second = client.post(
        f"/documents/{template}/web/batch",
        json={"account_ids": [account], "publish": False, "abm": True},
    ).json()
    assert second["manifest"][0]["document_id"] == doc_id
    assert "Acme Health Group" in str(repo.require_document(doc_id)["scene"])

    undone = client.post(f"/documents/{doc_id}/web/undo")

    assert undone.status_code == 200, undone.text
    assert repo.require_document(doc_id)["scene"] == scene_before


def test_an_unpublished_abm_batch_still_stamps_the_durable_flag(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """T27 review C-1, reproduced live there: the stamp sat inside `if publish:`, so an
    `{"abm": true, "publish": false}` run derived real ABM account pages UNSTAMPED — and the
    next plain publish (the editor button, no noindex field) served them indexed. The stamp
    rides the derive now, publish or not."""
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    account = _account(client, "Acme Health")

    body = client.post(
        f"/documents/{template}/web/batch",
        json={"account_ids": [account], "publish": False, "abm": True},
    ).json()
    doc_id = body["manifest"][0]["document_id"]

    repo = HybridRepository(workspace_id=workspace_id)
    assert repo.require_document(doc_id)["web_noindex"] is True
    # And the plain publish — no noindex field anywhere — serves the robots meta.
    published = client.post(f"/documents/{doc_id}/web/publish", json={"slug": "abm-later"})
    assert published.status_code == 200, published.text
    from lumen_api.web_export import ROBOTS_NOINDEX_META

    assert ROBOTS_NOINDEX_META in published_html(workspace_id, "abm-later")


def test_rollback_refuses_to_serve_a_stamped_page_unindexed(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """T27 review I-1, reproduced live there: rollback swaps STORED bytes, so a previous
    revision predating the stamp re-served the page indexed while the flag read True — the
    meta taken off with no explicit clearing act, by a tool a model role holds. It refuses
    now, naming the two honest ways out."""
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    account = _account(client, "Acme Health")
    derived = client.post(
        f"/documents/{template}/web/derive", json={"account_id": account}
    ).json()
    doc_id = derived["document_id"]
    # A page from before the stamp: born noindex since the founder ruling of 2026-10-16, so it
    # is made indexable explicitly to stand for one.
    assert (
        client.put(f"/documents/{doc_id}/web-noindex", json={"noindex": False}).status_code
        == 200
    )
    # First publish BEFORE any stamp (the pre-wave revision shape).
    first = client.post(f"/documents/{doc_id}/web/publish", json={"slug": "abm-rollbk"})
    assert first.status_code == 200, first.text
    # The explicit human act stamps it; the republish applies the meta.
    assert (
        client.put(f"/documents/{doc_id}/web-noindex", json={"noindex": True}).status_code
        == 200
    )
    second = client.post(f"/documents/{doc_id}/web/publish", json={"slug": "abm-rollbk"})
    assert second.status_code == 200, second.text

    rolled = client.post("/web/publishes/abm-rollbk/rollback")

    assert rolled.status_code in (409, 422), rolled.text
    assert "design_publish_rollback_would_unindex" in rolled.text
    from lumen_api.web_export import ROBOTS_NOINDEX_META

    assert ROBOTS_NOINDEX_META in published_html(workspace_id, "abm-rollbk")


def test_rollback_of_two_unstamped_revisions_stays_available(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """T27 delta D-1: a flag stamped AFTER both publishes means neither revision carries the
    meta — rolling back cannot worsen indexing, so a content rollback stays available."""
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    account = _account(client, "Acme Health")
    derived = client.post(
        f"/documents/{template}/web/derive", json={"account_id": account}
    ).json()
    doc_id = derived["document_id"]
    # Two unstamped revisions: the page is born noindex since the founder ruling of 2026-10-16,
    # so it is made indexable explicitly first.
    assert (
        client.put(f"/documents/{doc_id}/web-noindex", json={"noindex": False}).status_code
        == 200
    )
    assert client.post(f"/documents/{doc_id}/web/publish", json={"slug": "abm-2rev"}).status_code == 200
    assert client.post(f"/documents/{doc_id}/web/publish", json={"slug": "abm-2rev"}).status_code == 200
    assert (
        client.put(f"/documents/{doc_id}/web-noindex", json={"noindex": True}).status_code
        == 200
    )

    rolled = client.post("/web/publishes/abm-2rev/rollback")

    assert rolled.status_code == 200, rolled.text


def test_a_sprite_reference_svg_cannot_become_an_account_logo(
    workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """F4 wave item 2 (the CP2 walk's F-3): the ladder accepted a 124-byte sprite-reference
    SVG — no viewBox, no artwork — and the bind reported success while every derived page
    rendered a 0x0 nothing. The renderability predicate is the ladder's own, and the bind
    refuses by name before any durable write."""
    from lumen_ingestion.logo_ladder import svg_is_renderable

    sprite = b'<svg xmlns="http://www.w3.org/2000/svg"><use href="/sprite.svg#logo"></use></svg>'
    real = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 24">'
        b'<path d="M0 0h100v24H0z"/></svg>'
    )
    assert svg_is_renderable(sprite) is False
    assert svg_is_renderable(real) is True
    # Internal <use> against local <defs> still paints — never over-refused.
    internal = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        b'<defs><path id="p" d="M0 0h10v10z"/></defs><use href="#p"/></svg>'
    )
    assert svg_is_renderable(internal) is True


def test_the_escape_route_audit_lists_off_page_doors_and_skips_legal_links() -> None:
    """F4 wave item 6 (the walk's F-1, the lite half): every absolute off-page anchor on a
    noindex page is SAID on the manifest — except the footer's own legal links, which the
    rubric allows. Listed, never refused (a clone's anchors are D-F6 evidence)."""
    from lumen_api.web_export import _escape_route_audit

    html = (
        '<a href="https://press.example/story">press</a>'
        '<a class="lumen-shell-legal x" href="https://seller.example/privacy">Privacy</a>'
        '<a href="#contact">CTA</a>'
        '<a href="/relative">rel</a>'
        '<a href="https://press.example/story">dupe</a>'
        '<a href="https://seller.example/docs">docs</a>'
    )

    assert _escape_route_audit(html) == [
        "https://press.example/story",
        "https://seller.example/docs",
    ]


def test_the_composed_header_can_shrink_and_caps_the_target_mark() -> None:
    """F4 wave item 3 (the walk's F-5): a real bound logo made the strip 461px wide at a
    375px viewport. The marks group wraps and shrinks; the target mark is width-capped."""
    from lumen_api.fragments.campaign_shell import compose_campaign_header

    html = compose_campaign_header(seller_name="Insight Health", seller_logo_asset_id="l1")

    assert "min-w-0 flex-wrap" in html
    assert "max-w-40" in html


def test_the_bind_door_refuses_the_walks_sprite_and_stamps_nothing(
    client: TestClient, workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    """Wave round 2 (the re-walk's N-2 — the door had NO test; reverting it left every suite
    green): the CP2 walk's sprite shape, through the REAL binder — refused by name, account
    unstamped, registry unregistered. The fail-open read path is also closed (N-4): this door
    can refuse, never skip."""
    sprite = (
        b'<svg xmlns="http://www.w3.org/2000/svg">'
        b'<use href="/sprite.svg#logo"></use></svg>'
    )
    cache = tmp_path / "cache"
    _stage_bytes(cache, sprite)
    record = _fetched_record(sprite, asset_id="asset_ing_spritespritespri")
    record["kind"] = "vector_image"
    record["media"]["mime_type"] = "image/svg+xml"
    account = _account(client, "Cityblock Health")

    from lumen_api.agent_account_logos import AccountLogoRefused

    with pytest.raises(AccountLogoRefused) as refusal:
        _binder(client, workspace_id, design_storage, cache).bind(
            account_id=account, record=dict(record)
        )

    assert refusal.value.code == "account_logo.no_renderable_mark"
    repo = HybridRepository(workspace_id=workspace_id)
    assert repo.require_web_account(account)["logo_asset_id"] is None
    with pytest.raises(Exception):
        repo.require_asset_record(record["id"])
