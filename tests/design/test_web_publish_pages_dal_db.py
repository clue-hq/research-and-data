"""F5 Task 10 acceptance: a published site stores ONE HTML PER ROUTE.

Two tables back the property, and this test pins the seam between them:

* ``design_web_publish_revision_page`` — immutable, one row per
  ``(publish_id, workspace_id, route)``, born with its parent revision and never updated or
  deleted (the parent's own append-only rule).
* ``design_web_publish_page`` — the *materialized* current site: whatever the currently-served
  revision's pages are, and nothing else. It is derived, so publishing replaces it wholesale and
  rolling back re-materializes it from the revision that swaps back in.

The single scenario walks the property end to end: publish v1 with two routes (``/`` and
``/pricing``) → ``/pricing`` serves; publish v2 with only ``/`` → ``/pricing`` is GONE (a route
dropped from the new revision must stop serving, not linger); roll back → ``/pricing`` is back
with **v1's** html, because rollback re-materializes from the previous revision's own pages.

DB-gated like its neighbours (``test_dal_foundation_db.py``): skips without a reachable
``CLUE_DATABASE_URL``, and every write runs inside a transaction that is rolled back, so the test
leaves no rows behind.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import publishes
from tests.design.conftest import run_async


def _ws(tag: str) -> str:
    return f"ws_test_pubpages_{tag}_{uuid4().hex[:12]}"


async def _seed_web_doc(conn: AsyncConnection, doc_id: str, workspace_id: str) -> None:
    """Seed the workspace + a ``web`` design document (the publish FKs' parent)."""
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"),
        {"w": workspace_id},
    )
    await conn.execute(
        text(
            "INSERT INTO design_document"
            " (id, workspace_id, title, status, doc_kind, current_scene_json)"
            " VALUES (:d, :w, 'Site', 'draft', 'web', '{}'::jsonb)"
        ),
        {"d": doc_id, "w": workspace_id},
    )


def test_publish_pages_materialize_and_roll_back(require_design_db: None) -> None:
    async def _check() -> None:
        ws, doc = _ws("mat"), f"doc_{uuid4().hex}"
        slug = "site"
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            await _seed_web_doc(conn, doc, ws)

            rev1 = {
                "slug": slug,
                "document_id": doc,
                "doc_version": 1,
                "html": "<h1>v1 home</h1>",
                "html_digest": "a" * 64,
                "manifest": {},
                "manifest_digest": "m1",
                "package_digest": "p1" * 32,
                "runtime_version": None,
                "pages": [
                    {
                        "route": "/",
                        "page_id": "home",
                        "html": "<h1>v1 home</h1>",
                        "html_digest": "a" * 64,
                    },
                    {
                        "route": "/pricing",
                        "page_id": "pricing",
                        "html": "<h1>v1 pricing</h1>",
                        "html_digest": "b" * 64,
                    },
                ],
            }
            await publishes.register_web_publish_revision(conn, workspace_id=ws, revision=rev1)
            await publishes.upsert_web_publish(
                conn,
                workspace_id=ws,
                slug=slug,
                document_id=doc,
                doc_version=1,
                html=rev1["html"],
                runtime_version=None,
                publish_id="webpub_" + rev1["package_digest"],
            )
            page = await publishes.get_web_publish_page(
                conn, workspace_id=ws, slug=slug, route="/pricing"
            )
            assert page is not None
            assert page["html"] == "<h1>v1 pricing</h1>"
            assert page["page_id"] == "pricing"
            assert {
                p["route"]
                for p in await publishes.list_web_publish_pages(conn, workspace_id=ws, slug=slug)
            } == {"/", "/pricing"}

            rev2 = {
                **rev1,
                "doc_version": 2,
                "package_digest": "p2" * 32,
                "html": "<h1>v2 home</h1>",
                "pages": [
                    {
                        "route": "/",
                        "page_id": "home",
                        "html": "<h1>v2 home</h1>",
                        "html_digest": "c" * 64,
                    }
                ],
            }
            await publishes.register_web_publish_revision(conn, workspace_id=ws, revision=rev2)
            await publishes.upsert_web_publish(
                conn,
                workspace_id=ws,
                slug=slug,
                document_id=doc,
                doc_version=2,
                html=rev2["html"],
                runtime_version=None,
                publish_id="webpub_" + rev2["package_digest"],
            )
            # A route dropped from the new revision stops serving — the current pages are the
            # new revision's pages, not a union with the old ones.
            assert (
                await publishes.get_web_publish_page(
                    conn, workspace_id=ws, slug=slug, route="/pricing"
                )
                is None
            )
            home = await publishes.get_web_publish_page(conn, workspace_id=ws, slug=slug, route="/")
            assert home is not None and home["html"] == "<h1>v2 home</h1>"

            await publishes.rollback_web_publish(conn, workspace_id=ws, slug=slug)
            back = await publishes.get_web_publish_page(
                conn, workspace_id=ws, slug=slug, route="/pricing"
            )
            assert back is not None and back["html"] == "<h1>v1 pricing</h1>"
            rolled_home = await publishes.get_web_publish_page(
                conn, workspace_id=ws, slug=slug, route="/"
            )
            assert rolled_home is not None and rolled_home["html"] == "<h1>v1 home</h1>"

            await txn.rollback()

    run_async(_check())


def test_a_revision_without_pages_leaves_the_current_pages_empty(
    require_design_db: None,
) -> None:
    """Pre-F5 callers pass no ``pages`` key at all (and the batch route will until Task 11).

    That must not fail: the revision registers, no revision pages are written, and the current
    pages materialize EMPTY — which the serving layer reads as "legacy single-html publish" and
    falls back to ``design_web_publish.html`` at ``/``.
    """

    async def _check() -> None:
        ws, doc = _ws("legacy"), f"doc_{uuid4().hex}"
        slug = "legacy-site"
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            await _seed_web_doc(conn, doc, ws)
            revision = {
                "slug": slug,
                "document_id": doc,
                "doc_version": 1,
                "html": "<h1>legacy</h1>",
                "html_digest": "d" * 64,
                "manifest": {},
                "manifest_digest": "m0",
                "package_digest": "q1" * 32,
                "runtime_version": None,
            }
            await publishes.register_web_publish_revision(conn, workspace_id=ws, revision=revision)
            await publishes.upsert_web_publish(
                conn,
                workspace_id=ws,
                slug=slug,
                document_id=doc,
                doc_version=1,
                html=revision["html"],
                runtime_version=None,
                publish_id="webpub_" + revision["package_digest"],
            )
            assert await publishes.list_web_publish_pages(conn, workspace_id=ws, slug=slug) == []
            assert (
                await publishes.get_web_publish_page(conn, workspace_id=ws, slug=slug, route="/")
                is None
            )
            await txn.rollback()

    run_async(_check())


def test_two_workspaces_sharing_a_content_address_do_not_share_pages(
    require_design_db: None,
) -> None:
    """``publish_id`` is a CONTENT ADDRESS, so two tenants publishing byte-identical output mint
    the SAME id — which is why ``design_web_publish_revision``'s own key is
    ``(publish_id, workspace_id)`` and the pages' key must be too.

    Keyed on ``(publish_id, route)`` alone, the second tenant's page insert would hit
    ``ON CONFLICT DO NOTHING`` against the first tenant's rows and then serve them. This pins that
    each workspace materializes its OWN bytes under the shared address.
    """

    async def _check() -> None:
        ws_a, ws_b = _ws("xta"), _ws("xtb")
        doc_a, doc_b = f"doc_{uuid4().hex}", f"doc_{uuid4().hex}"
        slug, digest = "shared", "e1" * 32
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            await _seed_web_doc(conn, doc_a, ws_a)
            await _seed_web_doc(conn, doc_b, ws_b)

            def _revision(doc: str, marker: str) -> dict:
                return {
                    "slug": slug,
                    "document_id": doc,
                    "doc_version": 1,
                    "html": f"<h1>{marker}</h1>",
                    "html_digest": "f" * 64,
                    "manifest": {},
                    "manifest_digest": "m1",
                    "package_digest": digest,
                    "runtime_version": None,
                    "pages": [
                        {
                            "route": "/",
                            "page_id": "home",
                            "html": f"<h1>{marker}</h1>",
                            "html_digest": "f" * 64,
                        }
                    ],
                }

            for ws, doc, marker in ((ws_a, doc_a, "tenant a"), (ws_b, doc_b, "tenant b")):
                await publishes.register_web_publish_revision(
                    conn, workspace_id=ws, revision=_revision(doc, marker)
                )
                await publishes.upsert_web_publish(
                    conn,
                    workspace_id=ws,
                    slug=slug,
                    document_id=doc,
                    doc_version=1,
                    html=f"<h1>{marker}</h1>",
                    runtime_version=None,
                    publish_id=f"webpub_{digest}",
                )

            page_a = await publishes.get_web_publish_page(
                conn, workspace_id=ws_a, slug=slug, route="/"
            )
            page_b = await publishes.get_web_publish_page(
                conn, workspace_id=ws_b, slug=slug, route="/"
            )
            assert page_a is not None and page_a["html"] == "<h1>tenant a</h1>"
            assert page_b is not None and page_b["html"] == "<h1>tenant b</h1>"
            await txn.rollback()

    run_async(_check())
