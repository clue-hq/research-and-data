"""Publishing a Puck site (Wave 2 Lane A, Task 21)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from clue_toolbelt import PreconditionFailed
from fastapi.testclient import TestClient
from py_lumen_config import settings
from sqlalchemy import text

from clue_design.publishes import SITE_DELIVERY_CSP_META
from conftest import (
    is_served,
    make_blob_store,
    make_client,
    published,
    published_html,
    published_manifest,
    published_page,
    published_page_html,
)
from lumen_api import site_publish
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app, web_default_slug
from lumen_api.site_render import RENDER_TIMEOUT, SiteRenderError
from lumen_api.web_export import ROBOTS_NOINDEX_META
from site_kit_support import (
    chromium_available,
    ensure_site_kit_dist,
    garner_brand,
    garner_site,
    garner_site_without_clones,
    hold_site_images,
    install_site_inputs,
    section_module,
    store_site,
    QUOTE_JS,
)
from test_agent_run_write_lock import finish_run, start_leg_run
from test_site_publish_package import cloned_brand, cloned_site, mint_fragment
from test_web_export import seed_document


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    ensure_site_kit_dist()
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def stored(client: TestClient, site: dict, brand: dict | None = None) -> dict:
    site, brand = hold_site_images(site, brand if brand is not None else garner_brand(), make_blob_store(client.app))
    store_site(site)
    install_site_inputs(client.app, brand)
    return site


def test_publish_serve_state_republish_and_unpublish(client: TestClient, workspace_id: str) -> None:
    stored(client, garner_site_without_clones("site_pub"))
    response = client.post("/documents/site_pub/site/publish", json={"slug": "acme-site"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["slug"] == "acme-site" and body["url"] == f"{body['public_origin']}/acme-site"
    assert body["routes"] == ["/", "/analysis"] and set(body["page_urls"]) == {"/", "/analysis"}
    html = published_html(workspace_id, "acme-site")
    assert f'<meta http-equiv="Content-Security-Policy" content="{SITE_DELIVERY_CSP_META}">' in html
    assert "<script" not in html.lower()
    assert published_manifest(workspace_id, "acme-site")["delivery"] == "site"
    assert published_page(workspace_id, "acme-site", "/analysis") is not None
    state = client.get("/documents/site_pub/site/publish").json()
    assert state["published"] is True and state["slug"] == "acme-site"
    again = client.post("/documents/site_pub/site/publish", json={"slug": "acme-site"})
    assert again.status_code == 200 and again.json()["previous_available"] is True
    assert client.delete("/web/publishes/acme-site").json()["status"] == "unpublished"


def test_a_missing_agent_section_module_refuses_and_publishes_nothing(client: TestClient, workspace_id: str) -> None:
    site = garner_site_without_clones("site_pub_missing")
    site["agent_sections"] = {"Quote": section_module("Quote", QUOTE_JS).digest}
    stored(client, site)  # install_site_inputs with no modules: the loader returns none
    response = client.post("/documents/site_pub_missing/site/publish", json={"slug": "missing-site"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "site_publish.section_module_missing"
    assert published(workspace_id, "missing-site") is None


def test_a_clone_the_registry_does_not_hold_refuses(client: TestClient, workspace_id: str) -> None:
    stored(client, garner_site("site_pub_clone"))
    response = client.post("/documents/site_pub_clone/site/publish", json={"slug": "clone-site"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "site_publish.clone_unresolved"
    assert published(workspace_id, "clone-site") is None


def test_each_publish_route_refuses_the_other_kind(client: TestClient) -> None:
    stored(client, garner_site_without_clones("site_pub_kind"))
    web = client.post("/documents", json={"doc_kind": "web", "title": "A web page"}).json()["document"]
    to_site = client.post(f"/documents/{web['id']}/site/publish", json={})
    assert to_site.status_code == 409 and to_site.json()["detail"]["code"] == "document.kind_unsupported"
    to_web = client.post("/documents/site_pub_kind/web/publish", json={})
    assert to_web.status_code == 409 and to_web.json()["detail"]["code"] == "document.kind_unsupported"


# ==============================================================================================
# Business-logic scenarios: the real composed app, the Postgres test DB, the blob store, the
# site-kit bundles and Chromium, end to end through the HTTP routes.
# ==============================================================================================

CSP_META = f'<meta http-equiv="Content-Security-Policy" content="{SITE_DELIVERY_CSP_META}">'
HOME_HEADING = "7.4% lower medical spend in year one. No plan changes."


@pytest.fixture()
def quiet_client(tmp_path: Path, design_storage, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """The client for the run-lock scenario: it seeds a running run row directly and offers no
    fleet work, so no embedded worker drains the shared queue beside it (the lock suites' rule)."""
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    ensure_site_kit_dist()
    monkeypatch.setattr(settings, "lumen_embedded_fleet_worker", False, raising=False)
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def publish(client: TestClient, document_id: str, **body: Any):
    headers = body.pop("headers", None)
    return client.post(f"/documents/{document_id}/site/publish", json=body, headers=headers)


def ok(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()


def refused(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    detail = response.json()["detail"]
    assert detail["code"] == code, detail
    return detail


def with_home_heading(site: dict, heading: str) -> dict:
    """The site with the home page's one section (Garner's StatsBand) given a new heading."""
    changed = copy.deepcopy(site)
    changed["pages"]["/"]["content"][0]["props"]["heading"] = heading
    return changed


def save_site(client: TestClient, document_id: str, site: dict) -> int:
    """A manual save through the editor's route, from the stored version; returns the new one."""
    base = client.get(f"/documents/{document_id}").json()["current_version"]
    response = client.put(f"/documents/{document_id}/site", json={"site": site, "base_version": base})
    assert response.status_code == 200, response.text
    return response.json()["document"]["current_version"]


def sql(query: str, **params: Any) -> list[dict]:
    repo = HybridRepository()

    async def run(conn):
        result = await conn.execute(text(query), {"w": repo.workspace_id, **params})
        return [dict(row) for row in result.mappings().all()]

    return repo._bridge._run(run)


def revisions(document_id: str) -> list[dict]:
    return sql(
        "SELECT publish_id, slug, doc_version FROM design_web_publish_revision"
        " WHERE workspace_id = :w AND document_id = :d ORDER BY created_at",
        d=document_id,
    )


def revision_pages(publish_id: str) -> list[dict]:
    return sql(
        "SELECT route, page_id, html, html_digest FROM design_web_publish_revision_page"
        " WHERE workspace_id = :w AND publish_id = :p ORDER BY route",
        p=publish_id,
    )


def locked_at() -> Any:
    rows = sql("SELECT locked_at FROM workspace_hostname WHERE workspace_id = :w AND kind = 'system'")
    return rows[0]["locked_at"] if rows else None


def served_routes(slug: str) -> list[str]:
    return [page["route"] for page in HybridRepository().list_web_publish_pages(slug)]


def assert_served_site(workspace_id: str, slug: str) -> dict[str, str]:
    """Every route of the site is on the air, each page script-free under the site policy."""
    assert is_served(workspace_id, slug), slug
    assert served_routes(slug) == ["/", "/analysis"]
    pages = {route: published_page_html(workspace_id, slug, route) for route in ("/", "/analysis")}
    for route, html in pages.items():
        assert CSP_META in html, route
        assert "<script" not in html.lower(), route
    return pages


# a. Republish after an edit, immutable revisions, content addressing ---------------------------


def test_a_republish_after_an_edit_serves_the_edit_and_keeps_every_revision(client: TestClient, workspace_id: str) -> None:
    site = stored(client, garner_site_without_clones("site_edit"))
    first = ok(publish(client, "site_edit", slug="edit-site"))
    assert first["previous_available"] is False and first["runtime_version"] is None
    assert HOME_HEADING in assert_served_site(workspace_id, "edit-site")["/"]
    first_revision = HybridRepository().require_web_publish_revision(first["publish_id"])
    first_pages = revision_pages(first["publish_id"])
    assert [page["route"] for page in first_pages] == ["/", "/analysis"]

    version = save_site(client, "site_edit", with_home_heading(site, "Marker heading two for Syracuse"))
    second = ok(publish(client, "site_edit", slug="edit-site"))
    assert second["publish_id"] != first["publish_id"]
    assert second["doc_version"] == version and second["doc_version"] > first["doc_version"]
    assert second["previous_available"] is True
    pages = assert_served_site(workspace_id, "edit-site")
    assert "Marker heading two for Syracuse" in pages["/"] and HOME_HEADING not in pages["/"]

    # The first revision is still there, byte for byte, pages included (immutable rows).
    assert HybridRepository().require_web_publish_revision(first["publish_id"]) == first_revision
    assert revision_pages(first["publish_id"]) == first_pages
    assert [row["publish_id"] for row in revisions("site_edit")] == [first["publish_id"], second["publish_id"]]

    # The unchanged document republished is the same content-addressed revision.
    third = ok(publish(client, "site_edit", slug="edit-site"))
    assert third["publish_id"] == second["publish_id"]
    assert third["package_digest"] == second["package_digest"] and third["html_digest"] == second["html_digest"]
    assert len(revisions("site_edit")) == 2


# b. Rollback (the slug route is kind-agnostic) --------------------------------------------------


def test_b_rollback_serves_the_previous_site_revision_on_every_route(client: TestClient, workspace_id: str) -> None:
    site = stored(client, garner_site_without_clones("site_roll"))
    first = ok(publish(client, "site_roll", slug="roll-site"))
    before = assert_served_site(workspace_id, "roll-site")
    save_site(client, "site_roll", with_home_heading(site, "Marker heading two for Syracuse"))
    second = ok(publish(client, "site_roll", slug="roll-site"))
    assert "Marker heading two for Syracuse" in assert_served_site(workspace_id, "roll-site")["/"]

    rolled = client.post("/web/publishes/roll-site/rollback")
    assert rolled.status_code == 200, rolled.text
    body = rolled.json()
    assert body["publish_id"] == first["publish_id"] and body["doc_version"] == first["doc_version"]
    assert body["status"] == "active"
    # Every route is the first revision's own page again, byte for byte, under the site policy.
    assert assert_served_site(workspace_id, "roll-site") == before
    assert published_manifest(workspace_id, "roll-site")["delivery"] == "site"
    state = client.get("/documents/site_roll/site/publish").json()
    assert state["publish_id"] == first["publish_id"] and state["previous_available"] is True
    assert {page["route"] for page in state["pages"]} == {"/", "/analysis"}
    assert second["publish_id"] != first["publish_id"]


# c. One address per document; slugs another document holds; bad and default slugs ---------------


def test_c_a_site_lives_at_one_address_and_cannot_take_another_documents_slug(client: TestClient, workspace_id: str) -> None:
    stored(client, garner_site_without_clones("site_move"))
    ok(publish(client, "site_move", slug="site-a"))
    assert 'href="/site-a/analysis"' in assert_served_site(workspace_id, "site-a")["/"]
    moved = ok(publish(client, "site_move", slug="site-b"))
    assert moved["url"] == f"{moved['public_origin']}/site-b"
    assert not is_served(workspace_id, "site-a") and published(workspace_id, "site-a")["status"] == "unpublished"
    home = assert_served_site(workspace_id, "site-b")["/"]
    assert 'href="/site-b/analysis"' in home and "/site-a/" not in home

    # A slug a WEB document already publishes: refused, and the web page is untouched.
    web = seed_document(client)
    ok(client.post(f"/documents/{web['id']}/web/publish", json={"slug": "taken-slug"}))
    web_before = published(workspace_id, "taken-slug")
    taken = refused(publish(client, "site_move", slug="taken-slug"), 409, "web_publish.slug_taken")
    assert "taken-slug" in taken["message"]
    assert published(workspace_id, "taken-slug") == web_before
    assert web_before["document_id"] == web["id"] and web_before["status"] == "active"
    assert is_served(workspace_id, "site-b")  # the refused move did not take the site down

    refused(publish(client, "site_move", slug="ab"), 422, "web_publish.bad_slug")
    refused(publish(client, "site_move", slug="Not_A_Slug"), 422, "web_publish.bad_slug")

    # No slug: the title-derived default, the same builder the web route uses.
    stored(client, garner_site_without_clones("site_default"))
    title = HybridRepository().require_document("site_default")["title"]
    default = ok(publish(client, "site_default"))
    assert default["slug"] == web_default_slug(title, "site_default")
    assert_served_site(workspace_id, default["slug"])


def test_c_after_a_move_the_state_names_the_address_the_document_now_lives_at(client: TestClient, workspace_id: str) -> None:
    """The share menu reads this state to show where the page is. After a move it must name the
    live address, not the one the move took off the air — on the site route and the web route
    alike (they share one state builder)."""
    stored(client, garner_site_without_clones("site_moved_state"))
    web = seed_document(client)
    for first, second, path in (
        ("state-site-a", "state-site-b", "/documents/site_moved_state/site/publish"),
        ("state-web-a", "state-web-b", f"/documents/{web['id']}/web/publish"),
    ):
        ok(client.post(path, json={"slug": first}))
        ok(client.post(path, json={"slug": second}))
        assert not is_served(workspace_id, first) and is_served(workspace_id, second)
    site_state = client.get("/documents/site_moved_state/site/publish").json()
    web_state = client.get(f"/documents/{web['id']}/web/publish").json()
    observed = {
        "site": (site_state["slug"], site_state["status"]),
        "web": (web_state["slug"], web_state["status"]),
    }
    assert observed == {"site": ("state-site-b", "active"), "web": ("state-web-b", "active")}


# d. Idempotency -----------------------------------------------------------------------------------


def test_d_a_keyed_retry_replays_the_first_publish(client: TestClient, workspace_id: str) -> None:
    stored(client, garner_site_without_clones("site_keyed"))
    # Indexable, so the conflicting `noindex=True` body below would visibly change the page if it
    # ran (a new site is born noindex since the founder ruling of 2026-10-16).
    ok(client.put("/documents/site_keyed/web-noindex", json={"noindex": False}))
    headers = {"Idempotency-Key": "site-publish-once"}
    first = ok(publish(client, "site_keyed", slug="keyed-site", headers=headers))
    again = ok(publish(client, "site_keyed", slug="keyed-site", headers=headers))
    assert again == first
    # A second run would have rotated current -> previous; the replay did not.
    assert again["previous_available"] is False
    assert published(workspace_id, "keyed-site")["previous_html"] is None
    assert len(revisions("site_keyed")) == 1
    invocations = sql(
        "SELECT tool_name, status FROM tool_invocation WHERE workspace_id = :w AND tool_name = :t",
        t="design_publish_site@1",
    )
    assert invocations == [{"tool_name": "design_publish_site@1", "status": "completed"}]

    # The same key with a different body is a conflict, and changes nothing.
    conflict = publish(client, "site_keyed", slug="keyed-site", noindex=True, headers=headers)
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["error"] == "idempotency_conflict"
    assert published(workspace_id, "keyed-site")["previous_html"] is None
    assert ROBOTS_NOINDEX_META not in published_html(workspace_id, "keyed-site")

    # Without a key, a republish is a new operation: it rotates.
    assert ok(publish(client, "site_keyed", slug="keyed-site"))["previous_available"] is True


# e. noindex ---------------------------------------------------------------------------------------


def test_e_noindex_marks_every_page_and_the_documents_stored_flag_forces_it(client: TestClient, workspace_id: str) -> None:
    stored(client, garner_site_without_clones("site_index"))
    # Founder ruling 2026-10-16: a new site is born noindex; "Allow indexing" makes it indexable.
    ok(client.put("/documents/site_index/web-noindex", json={"noindex": False}))
    ok(publish(client, "site_index", slug="indexed-site"))
    assert "robots" not in published_manifest(workspace_id, "indexed-site")
    assert all(ROBOTS_NOINDEX_META not in html for html in assert_served_site(workspace_id, "indexed-site").values())

    stored(client, garner_site_without_clones("site_hidden"))
    ok(client.put("/documents/site_hidden/web-noindex", json={"noindex": False}))
    ok(publish(client, "site_hidden", slug="hidden-site", noindex=True))
    assert published_manifest(workspace_id, "hidden-site")["robots"] == "noindex"
    assert all(ROBOTS_NOINDEX_META in html for html in assert_served_site(workspace_id, "hidden-site").values())

    # K6-3: a site is stamped through the same route as a web page, and a plain republish of the
    # same document is then de-indexed on every page.
    assert ok(client.put("/documents/site_index/web-noindex", json={"noindex": True}))["web_noindex"] is True
    assert HybridRepository().require_document("site_index")["web_noindex"] is True
    stamped = ok(publish(client, "site_index", slug="indexed-site"))
    assert published_manifest(workspace_id, "indexed-site")["robots"] == "noindex"
    assert all(ROBOTS_NOINDEX_META in html for html in assert_served_site(workspace_id, "indexed-site").values())
    # And the kind-agnostic rollback guard covers it: rolling back would unindex the page.
    assert stamped["previous_available"] is True
    rollback = client.post("/web/publishes/indexed-site/rollback")
    assert rollback.status_code == 422, rollback.text
    assert rollback.json()["detail"]["reason_codes"] == ["design_publish_rollback_would_unindex"]
    assert all(ROBOTS_NOINDEX_META in html for html in assert_served_site(workspace_id, "indexed-site").values())


# k. K6-2/K6-3: the publish state says what changed since publishing and how the site is indexed --


def test_k_the_state_reports_changes_since_publishing_and_a_noindex_choice_survives_republishing(
    client: TestClient, workspace_id: str
) -> None:
    site = stored(client, garner_site_without_clones("site_k"))
    state = client.get("/documents/site_k/site/publish").json()
    # Founder ruling 2026-10-16: a new site is born noindex ("Allow indexing" starts unticked).
    assert (state["published"], state["noindex"], state["current_version"]) == (False, True, 0)

    # A publish that asks for nothing (as a reloaded menu used to send) cannot make the page indexable.
    first = ok(publish(client, "site_k", slug="k-site", noindex=False))
    assert all(ROBOTS_NOINDEX_META in html for html in assert_served_site(workspace_id, "k-site").values())
    state = client.get("/documents/site_k/site/publish").json()
    assert state["noindex"] is True
    assert state["doc_version"] == state["current_version"] == first["doc_version"]

    # The site changes after publishing: the state shows the live version is behind.
    version = save_site(client, "site_k", with_home_heading(site, "Changes since you published"))
    state = client.get("/documents/site_k/site/publish").json()
    assert state["current_version"] == version and state["doc_version"] == first["doc_version"] < version

    # Republishing catches up, still noindex on every page.
    second = ok(publish(client, "site_k", slug="k-site", noindex=False))
    state = client.get("/documents/site_k/site/publish").json()
    assert state["doc_version"] == state["current_version"] == second["doc_version"] == version
    pages = assert_served_site(workspace_id, "k-site")
    assert all(ROBOTS_NOINDEX_META in html for html in pages.values())
    assert "Changes since you published" in pages["/"]

    # Ticking "Allow indexing" again is an explicit act on the same route, and the next publish obeys it.
    assert ok(client.put("/documents/site_k/web-noindex", json={"noindex": False}))["web_noindex"] is False
    assert client.get("/documents/site_k/site/publish").json()["noindex"] is False
    ok(publish(client, "site_k", slug="k-site", noindex=False))
    assert all(ROBOTS_NOINDEX_META not in html for html in assert_served_site(workspace_id, "k-site").values())


def test_k_a_new_site_is_born_noindex_and_its_plain_publish_says_so_on_every_page(
    client: TestClient, workspace_id: str
) -> None:
    """Founder ruling 2026-10-16: every new site document is born with the durable noindex, so
    its first publish — a body that names no noindex at all — serves the robots meta on every
    page and in the manifest."""
    stored(client, garner_site_without_clones("site_born"))
    assert HybridRepository().require_document("site_born")["web_noindex"] is True
    ok(publish(client, "site_born", slug="born-site"))
    assert published_manifest(workspace_id, "born-site")["robots"] == "noindex"
    assert all(ROBOTS_NOINDEX_META in html for html in assert_served_site(workspace_id, "born-site").values())


def test_k_the_noindex_tool_takes_a_site_and_still_refuses_a_scene(client: TestClient, workspace_id: str) -> None:
    stored(client, garner_site_without_clones("site_k_tool"))
    tools = client.app.state.design_tools
    result = tools.invoke("design_set_web_noindex", {"document_id": "site_k_tool", "enabled": True}, workspace_id=workspace_id)
    assert result.references["value"] is True
    assert HybridRepository().require_document("site_k_tool")["web_noindex"] is True
    scene = client.post("/documents", json={}).json()["document"]["id"]
    with pytest.raises(PreconditionFailed) as not_website:
        tools.invoke("design_set_web_noindex", {"document_id": scene, "enabled": True}, workspace_id=workspace_id)
    assert not_website.value.reason_codes == ("design_document_not_web",)
    refused(client.put(f"/documents/{scene}/web-noindex", json={"noindex": True}), 409, "document.kind_unsupported")


# f. Refusals over HTTP; nothing is published for any of them ------------------------------------


def nothing_published(workspace_id: str, document_id: str, slug: str) -> None:
    assert published(workspace_id, slug) is None
    assert revisions(document_id) == []
    assert locked_at() is None  # nothing went on the air, so the label stays editable


def test_f_a_link_to_a_page_the_site_lacks_is_refused(client: TestClient, workspace_id: str) -> None:
    site = garner_site_without_clones("site_badlink")
    site["shell"]["header"]["nav"] = [{"label": "Pricing", "href": "/pricing"}]
    stored(client, site)  # stored directly, as an old row would be: the save route would refuse it
    detail = refused(publish(client, "site_badlink", slug="badlink-site"), 422, "site.invalid")
    assert any("links to /pricing, which is not a page of this site" in error for error in detail["errors"]), detail
    nothing_published(workspace_id, "site_badlink", "badlink-site")


def test_f_an_uncomposed_brand_loader_refuses_with_503(
    client: TestClient, workspace_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Lane B composes the app's real loader (site_workspace_view.site_brand_loader_for), so the app
    # default no longer refuses; a deployment without that composition still must, and says so.
    from lumen_api.site_doc_inputs import brand_loader_not_composed

    monkeypatch.setattr(client.app.state, "site_brand_loader", brand_loader_not_composed)
    site, _brand = hold_site_images(garner_site_without_clones("site_nobrand"), garner_brand(), make_blob_store(client.app))
    store_site(site)
    refused(publish(client, "site_nobrand", slug="nobrand-site"), 503, "site_inputs.unavailable")
    nothing_published(workspace_id, "site_nobrand", "nobrand-site")


def test_f_a_render_timeout_is_a_502_with_its_code(client: TestClient, workspace_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    stored(client, garner_site_without_clones("site_slow"))

    def timed_out(*_args: Any, **_kwargs: Any) -> Any:
        raise SiteRenderError(RENDER_TIMEOUT, "the site did not finish rendering in time")

    monkeypatch.setattr(site_publish, "render_site", timed_out)
    detail = refused(publish(client, "site_slow", slug="slow-site"), 502, RENDER_TIMEOUT)
    assert detail["message"] == "the site did not finish rendering in time"
    nothing_published(workspace_id, "site_slow", "slow-site")


def test_f_a_draft_clone_over_a_real_fragment_row_is_refused_in_the_founders_words(
    client: TestClient, workspace_id: str, design_storage
) -> None:
    draft = mint_fragment(design_storage, workspace_id, "draft")
    assert HybridRepository().find_web_fragment(draft)["status"] == "draft"
    brand = cloned_brand(draft)
    label = brand["clones"][draft]["label"]
    stored(client, cloned_site("site_draft", draft), brand)
    detail = refused(publish(client, "site_draft", slug="draft-site"), 409, "site_publish.clone_not_approved")
    assert detail["message"] == f'This page uses a section that isn\'t approved yet: "{label}". Approve your brand kit, then publish again.'
    nothing_published(workspace_id, "site_draft", "draft-site")


# g. The agent-run lock: parity with the web route -----------------------------------------------


def test_g_publishing_while_a_run_drives_the_document_matches_the_web_route(quiet_client: TestClient, workspace_id: str) -> None:
    client = quiet_client
    repo = HybridRepository()
    web = seed_document(client)
    stored(client, garner_site_without_clones("site_running"))
    outcomes: dict[str, int] = {}
    for kind, document_id, path, slug in (
        ("web", web["id"], f"/documents/{web['id']}/web/publish", "running-web"),
        ("site", "site_running", "/documents/site_running/site/publish", "running-site"),
    ):
        run_id = start_leg_run(repo, document_id)
        try:
            busy = client.get(f"/documents/{document_id}/agent-run").json()
            assert (busy["active"], busy["run_id"]) == (True, run_id)
            response = client.post(path, json={"slug": slug})
            outcomes[kind] = response.status_code
            served = is_served(workspace_id, slug)
        finally:
            finish_run(repo, run_id)
        assert response.json()["detail"] == {"code": "document.agent_run_active", "run_id": run_id}, kind
        assert served is False, kind
    # Founder ruling 2026-10-13: a person's publish waits for the run. main.py's
    # _refuse_if_agent_running guards BOTH publish routes (beside the six manual scene writes and the
    # site writes), so a publish mid-run is refused on the web route and the site route matches.
    assert outcomes == {"web": 409, "site": 409}
    # The run is over: the same publish goes through.
    ok(publish(client, "site_running", slug="running-site"))
    assert_served_site(workspace_id, "running-site")


# h. The hostname lock ---------------------------------------------------------------------------


def test_h_the_first_site_publish_locks_the_system_label(client: TestClient) -> None:
    stored(client, garner_site_without_clones("site_label"))
    assert locked_at() is None
    ok(publish(client, "site_label", slug="label-site"))
    first = locked_at()
    assert first is not None
    ok(publish(client, "site_label", slug="label-site"))
    assert locked_at() == first  # idempotent: never moves off the moment it first went public


# i. State: parity with the web route -------------------------------------------------------------


def test_i_the_publish_state_matches_the_web_route_before_and_after_an_unpublish(client: TestClient, workspace_id: str) -> None:
    stored(client, garner_site_without_clones("site_state"))
    web = seed_document(client)
    site_state = client.get("/documents/site_state/site/publish").json()
    web_state = client.get(f"/documents/{web['id']}/web/publish").json()
    assert set(site_state) == {"schema_version", "published", "public_origin", "custom_origin", "current_version", "noindex"}
    # The two documents differ in their own version; everything else about the state is the same.
    assert {**site_state, "current_version": None} == {**web_state, "current_version": None}
    assert site_state["published"] is False and site_state["custom_origin"] is None
    assert site_state["public_origin"].startswith("https://")

    body = ok(publish(client, "site_state", slug="state-site"))
    ok(client.post(f"/documents/{web['id']}/web/publish", json={"slug": "state-web"}))
    site_live = client.get("/documents/site_state/site/publish").json()
    web_live = client.get(f"/documents/{web['id']}/web/publish").json()
    assert set(site_live) == set(web_live)
    assert (site_live["published"], site_live["status"], site_live["slug"]) == (True, "active", "state-site")
    assert site_live["publish_id"] == body["publish_id"] and site_live["page_urls"] == body["page_urls"]

    for slug in ("state-site", "state-web"):
        assert client.delete(f"/web/publishes/{slug}").json()["status"] == "unpublished"
    site_after = client.get("/documents/site_state/site/publish").json()
    web_after = client.get(f"/documents/{web['id']}/web/publish").json()
    assert set(site_after) == set(web_after)
    assert (site_after["published"], site_after["status"]) == (web_after["published"], web_after["status"])
    assert site_after["status"] == "unpublished" and not is_served(workspace_id, "state-site")


# j. The tool itself, through the governed invoker the routes use ---------------------------------


def test_j_each_publish_tool_refuses_the_other_kind(client: TestClient, workspace_id: str) -> None:
    stored(client, garner_site_without_clones("site_tool"))
    web = seed_document(client)
    tools = client.app.state.design_tools
    with pytest.raises(PreconditionFailed) as not_site:
        tools.invoke("design_publish_site", {"document_id": web["id"], "slug": "tool-site"}, workspace_id=workspace_id)
    assert not_site.value.reason_codes == ("design_document_not_site",)
    with pytest.raises(PreconditionFailed) as not_web:
        tools.invoke("design_publish_web", {"document_id": "site_tool", "slug": "tool-web"}, workspace_id=workspace_id)
    assert not_web.value.reason_codes == ("design_document_not_web",)
    assert published(workspace_id, "tool-site") is None and published(workspace_id, "tool-web") is None

    # And the site tool publishes a site through the same invoker.
    result = tools.invoke("design_publish_site", {"document_id": "site_tool", "slug": "tool-site"}, workspace_id=workspace_id)
    assert result.references["routes"] == ["/", "/analysis"] and result.references["page_count"] == 2
    assert_served_site(workspace_id, "tool-site")
