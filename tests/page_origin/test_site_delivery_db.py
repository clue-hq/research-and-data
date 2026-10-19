"""A real site publish served by the real page origin (Wave 2 Contract 3: the per-publish CSP).

The route suite (``test_routes.py``) serves a ``FakePageReads``; this one writes the publish rows
the way a publish does (``register_web_publish_revision`` + ``upsert_web_publish``, which
materializes the per-route pages) and serves them through the origin's real routes over the real
``DbPageReads``: the hostname registry, the publish DAL's revision overlay, the page rows and the
manifest's ``delivery`` field are all read from Postgres.

How the app is built: ``clue_page_origin.main.build_application`` composes exactly
``create_page_origin_app(reads=DbPageReads(storage_from_settings(...)), gate=build_gate(settings,
secrets))`` plus a lifespan that sets up telemetry and opens the process engine over
``CLUE_DATABASE_URL``. Its reads would therefore only see COMMITTED rows, and committing publish
rows is not an option on a shared test database: ``design_web_publish_revision`` and its pages are
append-only by trigger, so they could never be cleaned up. So the app is composed the same way
minus the lifespan — the real ``build_gate`` over real ``Settings``/``Secrets``, the real
``DbPageReads`` bound to the test's rolled-back connection (a local ``FsStorage``; no page route
reads storage) — and driven over ``httpx.ASGITransport`` in the test's own event loop.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport

from clue_config import Secrets, Settings
from clue_design import publishes
from clue_design.documents import create_document
from clue_design.publishes import (
    DELIVERY_CSP_HEADER,
    PUBLISH_ASSET_MEDIA_TYPES,
    SITE_DELIVERY_CSP_HEADER,
    SITE_DELIVERY_CSP_META,
    site_live_csp,
)
from clue_design.storage import (
    SOURCE_KEY_PUBLISH_ASSET,
    SOURCE_KEY_SITE_SECTION,
    register_design_bytes,
)
from clue_page_origin import create_page_origin_app
from clue_page_origin.main import build_gate
from clue_page_origin.reads import DbPageReads
from clue_page_origin.routes import NOT_FOUND_HTML
from clue_spine import create_workspace
from clue_spine.hostnames import move_system_hostnames, system_hostname
from clue_spine.pages_settings import update_pages_settings
from clue_storage import FsStorage
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

from .conftest import SECRET, edge

_SUFFIX = "pages.test"


@pytest.fixture
def require_origin_db(migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_origin_db")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _site_html(title: str) -> str:
    """A script-free site page carrying the site policy as a meta tag (Contract 3's shape)."""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{SITE_DELIVERY_CSP_META}">'
        f"<title>{title}</title></head><body><main><h1>{title}</h1></main></body></html>"
    )


def _origin(conn: Any, tmp_path: Path, *, system_suffixes: tuple[str, ...] = ()) -> Any:
    settings = Settings(_env_file=None, pages_trust_host_header=False)  # type: ignore[call-arg]
    secrets = Secrets(_env_file=None, pages_edge_secret=SECRET)  # type: ignore[call-arg]
    reads = DbPageReads(
        FsStorage(tmp_path / "blobs"),
        conn_factory=conn_session_factory(conn),
        system_suffixes=system_suffixes,
    )
    return create_page_origin_app(reads=reads, gate=build_gate(settings, secrets))


async def _workspace(conn: Any) -> tuple[str, str]:
    """A workspace and the system hostname the registry allocated for it."""
    workspace = await create_workspace(
        conn, name=f"Site Origin {uuid4().hex[:6]}", pages_system_suffix=_SUFFIX
    )
    hostname = await system_hostname(conn, workspace.workspace_id)
    assert hostname is not None and hostname.endswith("." + _SUFFIX)
    return workspace.workspace_id, hostname


async def _document(conn: Any, workspace_id: str, *, doc_kind: str) -> str:
    document_id = f"doc_{doc_kind}_{uuid4().hex[:10]}"
    if doc_kind == "site":
        scene: dict[str, Any] = {
            "id": document_id,
            "title": "Syracuse",
            "theme": {},
            "pages": {
                "/": {"root": {"props": {"title": "Syracuse"}}, "content": []},
                "/analysis": {"root": {"props": {"title": "Analysis"}}, "content": []},
            },
            "shell": None,
            "agent_sections": {},
        }
    else:
        scene = {
            "schema_version": 1,
            "id": document_id,
            "title": "Annual report",
            "theme": {},
            "pages": [{"id": "home", "nodes": {"root": {"kind": "root"}}}],
        }
    document = await create_document(
        conn, workspace_id=workspace_id, scene=scene, doc_kind=doc_kind
    )
    return str(document["id"])


async def _publish(
    conn: Any,
    workspace_id: str,
    *,
    slug: str,
    document_id: str,
    manifest: dict[str, Any],
    pages: dict[str, str],
) -> None:
    """Publish ``pages`` (route → html) under ``slug`` the way the publish path writes it."""
    manifest_json = json.dumps(manifest, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    home = pages["/"]
    package_digest = _sha(f"{workspace_id}:{slug}:{manifest_json}:{sorted(pages.items())}")
    await publishes.register_web_publish_revision(
        conn,
        workspace_id=workspace_id,
        revision={
            "slug": slug,
            "document_id": document_id,
            "doc_version": 1,
            "html": home,
            "html_digest": _sha(home),
            "manifest": manifest,
            "manifest_digest": _sha(manifest_json),
            "package_digest": package_digest,
            "runtime_version": None,
            "pages": [
                {
                    "route": route,
                    "page_id": route.strip("/") or "home",
                    "html": html,
                    "html_digest": _sha(html),
                }
                for route, html in pages.items()
            ],
        },
    )
    await publishes.upsert_web_publish(
        conn,
        workspace_id=workspace_id,
        slug=slug,
        document_id=document_id,
        doc_version=1,
        html=home,
        runtime_version=None,
        publish_id=f"webpub_{package_digest}",
    )


async def _get(app: Any, host: str, path: str, *, method: str = "GET") -> httpx.Response:
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.request(method, path, headers=edge(host), follow_redirects=False)


def _assert_page(response: httpx.Response, *, body: str, csp: str, noindex: bool) -> None:
    assert response.status_code == 200, response.text
    assert response.text == body
    assert response.headers["content-security-policy"] == csp
    assert response.headers["etag"] == f'"sha256-{_sha(body)}"'
    assert response.headers["cache-control"] == "public, max-age=60, must-revalidate"
    assert response.headers["x-content-type-options"] == "nosniff"
    if noindex:
        assert response.headers["x-robots-tag"] == "noindex"
    else:
        assert "x-robots-tag" not in response.headers


def test_every_route_of_a_site_publish_is_served_under_the_site_policy(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws, host = await _workspace(conn)
            site = await _document(conn, ws, doc_kind="site")
            for slug, robots in (("syracuse", {}), ("syracuse-private", {"robots": "noindex"})):
                await _publish(
                    conn,
                    ws,
                    slug=slug,
                    document_id=site,
                    manifest={"slug": slug, "delivery": "site", **robots},
                    pages={"/": _site_html("Syracuse"), "/analysis": _site_html("Analysis")},
                )
            app = _origin(conn, tmp_path)

            for slug, noindex in (("syracuse", False), ("syracuse-private", True)):
                home = await _get(app, host, f"/{slug}")
                _assert_page(
                    home, body=_site_html("Syracuse"), csp=SITE_DELIVERY_CSP_HEADER, noindex=noindex
                )
                analysis = await _get(app, host, f"/{slug}/analysis")
                _assert_page(
                    analysis,
                    body=_site_html("Analysis"),
                    csp=SITE_DELIVERY_CSP_HEADER,
                    noindex=noindex,
                )
                # A trailing slash names the same route, under the same policy.
                trailing = await _get(app, host, f"/{slug}/analysis/")
                assert trailing.status_code == 200
                assert trailing.headers["content-security-policy"] == SITE_DELIVERY_CSP_HEADER
                head = await _get(app, host, f"/{slug}/analysis", method="HEAD")
                assert head.status_code == 200 and head.content == b""
                assert head.headers["content-security-policy"] == SITE_DELIVERY_CSP_HEADER

                manifest = await _get(app, host, f"/{slug}/manifest.json")
                assert manifest.status_code == 200, manifest.text
                assert manifest.headers["content-type"].startswith("application/json")
                assert manifest.json() == {
                    "slug": slug,
                    "delivery": "site",
                    **({"robots": "noindex"} if noindex else {}),
                }
                assert manifest.headers["content-security-policy"] == SITE_DELIVERY_CSP_HEADER
                assert manifest.headers["etag"] == f'"sha256-{_sha(manifest.text)}"'
                if noindex:
                    assert manifest.headers["x-robots-tag"] == "noindex"
                else:
                    assert "x-robots-tag" not in manifest.headers

    run_async(scenario())


_LIVE_HASH = "sha256-" + "B" * 43 + "="


# --- Review focus 4: the origin follows the publish's manifest, never the rollout flag ---------
def test_review_focus_4_a_live_publish_stays_live_whatever_the_flag_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``LUMEN_SITE_LIVE_WORKSPACES`` decides how a NEW publish is built; a publish already made
    live keeps its own policy (its manifest's ``delivery`` + ``live.script_hashes``) whatever the
    flag says now."""
    monkeypatch.setenv("LUMEN_SITE_LIVE_WORKSPACES", "")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws, host = await _workspace(conn)
            site = await _document(conn, ws, doc_kind="site")
            for slug, robots in (("syracuse", {}), ("syracuse-private", {"robots": "noindex"})):
                await _publish(
                    conn,
                    ws,
                    slug=slug,
                    document_id=site,
                    manifest={
                        "slug": slug,
                        "delivery": "site_live",
                        "live": {"runtime": _sha("runtime"), "script_hashes": [_LIVE_HASH]},
                        **robots,
                    },
                    pages={"/": _site_html("Syracuse"), "/analysis": _site_html("Analysis")},
                )
            app = _origin(conn, tmp_path)
            live_csp = site_live_csp([_LIVE_HASH], meta=False)

            for slug, noindex in (("syracuse", False), ("syracuse-private", True)):
                home = await _get(app, host, f"/{slug}")
                _assert_page(home, body=_site_html("Syracuse"), csp=live_csp, noindex=noindex)
                analysis = await _get(app, host, f"/{slug}/analysis")
                _assert_page(analysis, body=_site_html("Analysis"), csp=live_csp, noindex=noindex)
                trailing = await _get(app, host, f"/{slug}/analysis/")
                assert trailing.status_code == 200
                assert trailing.headers["content-security-policy"] == live_csp
                head = await _get(app, host, f"/{slug}/analysis", method="HEAD")
                assert head.status_code == 200 and head.content == b""
                assert head.headers["content-security-policy"] == live_csp

                manifest = await _get(app, host, f"/{slug}/manifest.json")
                assert manifest.status_code == 200, manifest.text
                assert manifest.json()["delivery"] == "site_live"
                assert manifest.json()["live"]["script_hashes"] == [_LIVE_HASH]
                assert manifest.headers["content-security-policy"] == live_csp
                assert manifest.headers["etag"] == f'"sha256-{_sha(manifest.text)}"'
                if noindex:
                    assert manifest.headers["x-robots-tag"] == "noindex"
                else:
                    assert "x-robots-tag" not in manifest.headers

    run_async(scenario())


def test_everything_that_is_not_exactly_a_site_publish_keeps_the_web_policy(
    tmp_path: Path,
) -> None:
    """``delivery`` must say exactly ``site``: no field, ``"SITE"`` and ``"web"`` are all web."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws, host = await _workspace(conn)
            web = await _document(conn, ws, doc_kind="web")
            site = await _document(conn, ws, doc_kind="site")
            cases = {
                "annual-report": (web, {"slug": "annual-report"}),
                "shouting": (site, {"slug": "shouting", "delivery": "SITE"}),
                "said-web": (site, {"slug": "said-web", "delivery": "web"}),
            }
            for slug, (document_id, manifest) in cases.items():
                await _publish(
                    conn,
                    ws,
                    slug=slug,
                    document_id=document_id,
                    manifest=manifest,
                    pages={"/": f"<html>{slug} home</html>", "/analysis": f"<html>{slug} a</html>"},
                )
            app = _origin(conn, tmp_path)

            for slug, (_document_id, manifest) in cases.items():
                _assert_page(
                    await _get(app, host, f"/{slug}"),
                    body=f"<html>{slug} home</html>",
                    csp=DELIVERY_CSP_HEADER,
                    noindex=False,
                )
                _assert_page(
                    await _get(app, host, f"/{slug}/analysis"),
                    body=f"<html>{slug} a</html>",
                    csp=DELIVERY_CSP_HEADER,
                    noindex=False,
                )
                served = await _get(app, host, f"/{slug}/manifest.json")
                assert served.status_code == 200
                assert served.json() == manifest
                assert served.headers["content-security-policy"] == DELIVERY_CSP_HEADER, slug

    run_async(scenario())


def _miss_shape(response: httpx.Response) -> tuple[Any, ...]:
    """Everything a visitor can observe of a miss."""
    return (
        response.status_code,
        response.text,
        response.headers.get("location"),
        response.headers.get("x-robots-tag"),
        response.headers.get("cache-control"),
        response.headers.get("content-security-policy"),
    )


def test_an_unpublished_site_and_an_unknown_route_answer_exactly_as_for_web(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws, host = await _workspace(conn)
            site = await _document(conn, ws, doc_kind="site")
            web = await _document(conn, ws, doc_kind="web")
            for slug, document_id, manifest in (
                ("gone-site", site, {"slug": "gone-site", "delivery": "site"}),
                ("gone-web", web, {"slug": "gone-web"}),
                ("live-site", site, {"slug": "live-site", "delivery": "site"}),
                ("live-web", web, {"slug": "live-web"}),
            ):
                await _publish(
                    conn,
                    ws,
                    slug=slug,
                    document_id=document_id,
                    manifest=manifest,
                    pages={"/": "<html>home</html>", "/analysis": "<html>analysis</html>"},
                )
            for slug in ("gone-site", "gone-web"):
                assert await publishes.set_web_publish_status(
                    conn, workspace_id=ws, slug=slug, status="unpublished"
                )
            app = _origin(conn, tmp_path)

            pairs = [
                *(
                    (f"/gone-site{tail}", f"/gone-web{tail}")
                    for tail in ("", "/analysis", "/manifest.json")
                ),
                ("/live-site/nope", "/live-web/nope"),
                ("/live-site/docs/intro", "/live-web/docs/intro"),
            ]
            # No fallback URL: the origin's 404 page, the shape test_routes.py pins for web.
            for site_path, web_path in pairs:
                site_miss = await _get(app, host, site_path)
                web_miss = await _get(app, host, web_path)
                assert _miss_shape(site_miss) == _miss_shape(web_miss), site_path
                assert site_miss.status_code == 404
                assert site_miss.text == NOT_FOUND_HTML
                assert site_miss.headers["x-robots-tag"] == "noindex"
                assert "content-security-policy" not in site_miss.headers

            # With a fallback URL: the same 302 to it, for site and web alike.
            await update_pages_settings(
                conn, workspace_id=ws, fallback_url="https://www.syracuse.example"
            )
            for site_path, web_path in pairs:
                site_miss = await _get(app, host, site_path)
                web_miss = await _get(app, host, web_path)
                assert _miss_shape(site_miss) == _miss_shape(web_miss), site_path
                assert site_miss.status_code == 302
                assert site_miss.headers["location"] == "https://www.syracuse.example"

    run_async(scenario())


# --- Review finding K3-6: both addresses serve while published pages move domain ---------------
def test_k3_6_a_system_address_is_served_on_the_old_and_the_new_domain_before_and_after_the_move(
    tmp_path: Path,
) -> None:
    """The runbook turns the edge's 301 on last, but the rows may move at any point before it: a
    page must answer at `<label>.<old>` and `<label>.<new>` whichever domain its row names."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            tag = uuid4().hex[:6]
            old, new = f"old{tag}.test", f"new{tag}.test"
            workspace = await create_workspace(
                conn, name=f"Move Origin {tag}", pages_system_suffix=old
            )
            ws = workspace.workspace_id
            born = await system_hostname(conn, ws)
            assert born is not None
            label = born.removesuffix("." + old)
            web = await _document(conn, ws, doc_kind="web")
            await _publish(
                conn,
                ws,
                slug="annual-report",
                document_id=web,
                manifest={"slug": "annual-report"},
                pages={"/": "<html>report</html>"},
            )
            # The page origin as main.py composes it after step 3: new suffix + the old one.
            app = _origin(conn, tmp_path, system_suffixes=(new, old))

            async def answers() -> dict[str, int]:
                hosts = (f"{label}.{old}", f"{label}.{new}", f"x.{label}.{new}", f"{label}.x.test")
                return {
                    host: (await _get(app, host, "/annual-report")).status_code for host in hosts
                }

            expected = {
                f"{label}.{old}": 200,
                f"{label}.{new}": 200,
                # Not a system address: an extra label before the suffix, or a suffix not served.
                f"x.{label}.{new}": 404,
                f"{label}.x.test": 404,
            }
            assert await answers() == expected  # the row still names the old domain
            report = await move_system_hostnames(conn, from_suffix=old, to_suffix=new, apply=True)
            assert (report["rows"], report["applied"]) == (1, True)
            assert await answers() == expected  # the row now names the new domain

    run_async(scenario())


def test_an_agent_sections_module_saved_by_the_section_tool_is_served_after_a_live_publish(
    tmp_path: Path,
) -> None:
    """Found on the live walk (2026-10-15): the section tool stores a compiled module as
    ``text/javascript``; the publish then registers the same bytes as a page asset, but the digest
    already has its artifact row, so the row keeps the section tool's type. The page origin must
    still serve that module, or the published page loses the section after hydration."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws, host = await _workspace(conn)
            storage = FsStorage(tmp_path / "blobs")
            module = b"export function render() { return null; }\n"
            digest = hashlib.sha256(module).hexdigest()
            # The order a real turn and publish use: the section tool, then the publish.
            await register_design_bytes(
                conn,
                storage,
                workspace_id=ws,
                data=module,
                media_type="text/javascript",
                source_key=SOURCE_KEY_SITE_SECTION,
            )
            await register_design_bytes(
                conn,
                storage,
                workspace_id=ws,
                data=module,
                media_type=PUBLISH_ASSET_MEDIA_TYPES["js"],
                source_key=SOURCE_KEY_PUBLISH_ASSET,
            )
            app = _origin(conn, tmp_path)

            served = await _get(app, host, f"/p-assets/{digest}.js")
            assert served.status_code == 200, served.text
            assert served.content == module
            assert served.headers["content-type"] == PUBLISH_ASSET_MEDIA_TYPES["js"]
            # The type still has to agree with the address: never served as a stylesheet.
            assert (await _get(app, host, f"/p-assets/{digest}.css")).status_code == 404

    run_async(scenario())
