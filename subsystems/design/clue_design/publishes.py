"""Web-publish DAL (Part II slice D2.4B) — the port of the design API's ``web_publishes`` /
``web_publish_revisions`` domain.

Faithful port of ``lumen_api.database.Repository``'s publish methods onto
``design_web_publish`` + ``design_web_publish_revision`` (PD contract §5 rows 19–20), with the
D1/D2 upgrades the contract mandates:

* **Fail-closed tenancy, and slugs are workspace-LOCAL (O6, ratified).** ``design_web_publish``
  is keyed ``(workspace_id, slug)``: two tenants may both publish ``pricing`` and neither can
  see, overwrite, or 409 the other. Global URL uniqueness became a *serving-layer* concern —
  which is why the public route is workspace-scoped at D2 (O6b, ratified option (a):
  ``/w/{workspace_id}/p/{slug}``; Part IV owns the real routing and deletes the interim route).
* **Real FKs where SQLite validated by convention.** ``document_id`` references
  ``design_document (id, workspace_id)`` (NO ACTION — publish history pins a document's
  provenance), and both ``publish_id`` / ``previous_publish_id`` reference
  ``design_web_publish_revision (publish_id, workspace_id)``, so the live serving row can no
  longer point at a revision that does not exist.
* **Content-addressing is structural.** ``design_web_publish_revision_content_address`` CHECKs
  ``publish_id = 'webpub_' || package_digest`` — the SQLite era enforced that only by the
  caller's naming convention. :func:`register_web_publish_revision` therefore *derives* the id
  from the package digest rather than trusting the caller's, and still runs the ported
  equal-content comparison so a digest collision with different content is a loud ``ValueError``
  instead of a silent no-op.
* **Append-only history.** UPDATE *and* DELETE on ``design_web_publish_revision`` are rejected by
  trigger, so this module is INSERT-only on revisions (the SQLite code already was: unpublish
  flips ``design_web_publish.status``, it never touches history).
* **F5: a published site is one HTML per ROUTE.** ``design_web_publish_revision_page`` holds a
  package's pages (immutable with their parent) and ``design_web_publish_page`` holds the
  *materialized* current site — re-derived wholesale from whichever package is being served, by
  both :func:`upsert_web_publish` and :func:`rollback_web_publish`, inside their own transaction.
  ``design_web_publish.html`` still carries the ``/`` page, so pre-F5 readers are untouched, and a
  package registered without pages simply materializes none — the serving layer reads that empty
  state as a legacy single-html publish rather than a broken one.

The two atomic swaps keep their single-statement semantics exactly:
:func:`upsert_web_publish` is ONE ``INSERT … ON CONFLICT DO UPDATE`` whose ``SET`` list reads the
*existing* row into ``previous_*`` while writing the new payload, and
:func:`rollback_web_publish` is ONE ``UPDATE`` whose ``SET`` expressions all evaluate against the
original row, so current/previous swap atomically. Neither can observe a half-swapped row.

Callers own the transaction (one logical operation = one transaction — the O5 rule); nothing
here commits. Mappers reproduce ``web_publish_from_row`` / ``web_publish_revision_from_row``
exactly, with ISO-string timestamps.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, iso, load_json
from clue_design.errors import DesignArtifactConflictError, DesignNotFoundError

# The columns the ported equal-content check compares when a publish id is re-registered.
_REVISION_COMPARABLE = (
    "publish_id",
    "slug",
    "document_id",
    "doc_version",
    "html",
    "html_digest",
    "manifest",
    "manifest_digest",
    "package_digest",
    "runtime_version",
)


def _web_publish_from_row(row: Any) -> JsonObject:
    return {
        "slug": row.slug,
        "document_id": row.document_id,
        "doc_version": row.doc_version,
        "html": row.html,
        "previous_html": row.previous_html,
        "previous_doc_version": row.previous_doc_version,
        "runtime_version": row.runtime_version,
        "status": row.status,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
        "publish_id": row.publish_id,
        "previous_publish_id": row.previous_publish_id,
    }


def _web_publish_revision_from_row(row: Any) -> JsonObject:
    return {
        "publish_id": row.publish_id,
        "slug": row.slug,
        "document_id": row.document_id,
        "doc_version": row.doc_version,
        "html": row.html,
        "html_digest": row.html_digest,
        "manifest": load_json(row.manifest_json),
        "manifest_digest": row.manifest_digest,
        "package_digest": row.package_digest,
        "runtime_version": row.runtime_version,
        "created_at": iso(row.created_at),
    }


# --- publish revisions (immutable, content-addressed) ----------------------------------------


async def require_web_publish_revision(
    conn: AsyncConnection, *, workspace_id: str, publish_id: str
) -> JsonObject:
    """Fetch one immutable publish package or raise."""
    row = (
        await conn.execute(
            text(
                "SELECT * FROM design_web_publish_revision"
                " WHERE publish_id = :p AND workspace_id = :w"
            ),
            {"p": publish_id, "w": workspace_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("web_publish_revision", publish_id)
    return _web_publish_revision_from_row(row)


async def register_web_publish_revision(
    conn: AsyncConnection, *, workspace_id: str, revision: JsonObject
) -> JsonObject:
    """Append one immutable, content-identified publish package (INSERT-only; ported).

    ``publish_id`` is *derived* from ``package_digest`` rather than taken on trust, because
    ``design_web_publish_revision_content_address`` makes the address structural — a caller that
    mints ``webpub_<digest>`` (both call sites do) sees no change, and one that does not is
    corrected here instead of failing on a CHECK it cannot read. The ported equal-content
    comparison survives verbatim: re-registering an existing id with different content is a
    ``ValueError``, never a silent overwrite (the row is immutable by trigger anyway).

    ``created_at`` comes from the column default rather than the caller's ``utc_now()`` string:
    the timestamp is server-authoritative here, it is not part of the content address, and both
    call sites passed exactly the value the default produces.

    F5: ``revision`` may carry ``"pages"`` — ``[{"route", "page_id", "html", "html_digest"}]`` —
    which lands in ``design_web_publish_revision_page`` under the same ``ON CONFLICT DO NOTHING``
    idempotency as the parent (re-registering the same package is a no-op, and the rows are
    immutable by trigger anyway, so a rewrite is not merely skipped, it is impossible). The key
    is **optional**: pre-F5 callers pass no ``pages`` at all, and then the package simply has
    none — its current pages materialize empty and the serving layer falls back to the legacy
    single ``html`` at ``/``.
    """
    publish_id = f"webpub_{revision['package_digest']}"
    await conn.execute(
        text(
            """
            INSERT INTO design_web_publish_revision (
              publish_id, workspace_id, slug, document_id, doc_version, html, html_digest,
              manifest_json, manifest_digest, package_digest, runtime_version
            )
            VALUES (:p, :w, :slug, :doc, :doc_version, :html, :html_digest,
                    CAST(:manifest AS jsonb), :manifest_digest, :package_digest, :runtime)
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "p": publish_id,
            "w": workspace_id,
            "slug": revision["slug"],
            "doc": revision["document_id"],
            "doc_version": revision["doc_version"],
            "html": revision["html"],
            "html_digest": revision["html_digest"],
            "manifest": dump_json(revision["manifest"]),
            "manifest_digest": revision["manifest_digest"],
            "package_digest": revision["package_digest"],
            "runtime": revision.get("runtime_version"),
        },
    )
    pages = revision.get("pages") or []
    for page in pages:
        await conn.execute(
            text(
                """
                INSERT INTO design_web_publish_revision_page (
                  publish_id, workspace_id, route, page_id, html, html_digest
                )
                VALUES (:p, :w, :route, :page_id, :html, :html_digest)
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "p": publish_id,
                "w": workspace_id,
                "route": page["route"],
                "page_id": page["page_id"],
                "html": page["html"],
                "html_digest": page["html_digest"],
            },
        )
    stored = await require_web_publish_revision(
        conn, workspace_id=workspace_id, publish_id=publish_id
    )
    expected = {key: revision.get(key) for key in _REVISION_COMPARABLE}
    expected["publish_id"] = publish_id
    if {key: stored.get(key) for key in _REVISION_COMPARABLE} != expected:
        # D6 Round C: this was a bare ``ValueError`` nothing caught — a 500 for what is a
        # perfectly describable domain refusal. It is the same species the component registry
        # already names (a content-addressed id re-used with different content), so it raises the
        # same taxonomy error and the API turns it into a 409 rather than a database.error.
        raise DesignArtifactConflictError("web_publish_revision", publish_id)
    return stored


# --- per-route pages (F5 multi-page publishing) -----------------------------------------------


async def materialize_web_publish_pages(
    conn: AsyncConnection, *, workspace_id: str, slug: str, publish_id: str | None
) -> None:
    """Re-derive ``design_web_publish_page`` from the revision that ``slug`` now serves.

    Delete-then-insert, wholesale and inside the caller's transaction: the current site is
    **exactly** the pages of ``publish_id``, never a union with what was there before. That is
    what makes a route dropped from a new revision stop serving, and what lets rollback restore a
    route by simply re-running this against the revision that swapped back in.

    ``publish_id=None`` (a publish row that pins no package) clears the pages and inserts none —
    the same honest empty state a package without pages produces, which the serving layer reads
    as "legacy single-html publish".

    The source read is workspace-scoped as well as id-scoped: ``publish_id`` is a content address
    two tenants can legitimately share, so ``workspace_id`` is half of the revision pages' key,
    not a redundant filter.
    """
    await conn.execute(
        text("DELETE FROM design_web_publish_page WHERE workspace_id = :w AND slug = :s"),
        {"w": workspace_id, "s": slug},
    )
    if publish_id is None:
        return
    await conn.execute(
        text(
            """
            INSERT INTO design_web_publish_page (
              workspace_id, slug, route, page_id, html, html_digest
            )
            SELECT :w, :s, route, page_id, html, html_digest
              FROM design_web_publish_revision_page
             WHERE publish_id = :p AND workspace_id = :w
            """
        ),
        {"w": workspace_id, "s": slug, "p": publish_id},
    )


async def get_web_publish_page(
    conn: AsyncConnection, *, workspace_id: str, slug: str, route: str
) -> JsonObject | None:
    """One served route's HTML, or ``None`` — the serving layer's per-route read.

    ``None`` covers both "this site has no such route" and "this site has no pages at all"
    (a pre-F5 publish); the caller distinguishes them by falling back to the publish row's own
    ``html`` for ``/`` only.
    """
    row = (
        await conn.execute(
            text(
                "SELECT route, page_id, html, html_digest FROM design_web_publish_page"
                " WHERE workspace_id = :w AND slug = :s AND route = :r"
            ),
            {"w": workspace_id, "s": slug, "r": route},
        )
    ).first()
    if row is None:
        return None
    return {
        "route": row.route,
        "page_id": row.page_id,
        "html": row.html,
        "html_digest": row.html_digest,
    }


async def list_web_publish_pages(
    conn: AsyncConnection, *, workspace_id: str, slug: str
) -> list[JsonObject]:
    """Every route a site currently serves, WITHOUT the html — the index read.

    Deliberately html-free: this backs sitemaps, route listings and "what did we publish?"
    surfaces, none of which want a whole site's markup in one response. Fetch a page's bytes with
    :func:`get_web_publish_page`.
    """
    rows = (
        await conn.execute(
            text(
                "SELECT route, page_id, html_digest FROM design_web_publish_page"
                " WHERE workspace_id = :w AND slug = :s ORDER BY route"
            ),
            {"w": workspace_id, "s": slug},
        )
    ).fetchall()
    return [
        {"route": row.route, "page_id": row.page_id, "html_digest": row.html_digest} for row in rows
    ]


# --- the live serving row --------------------------------------------------------------------


async def get_web_publish(
    conn: AsyncConnection, *, workspace_id: str, slug: str
) -> JsonObject | None:
    """The optional read (the endpoints' publish probe): ``None``, never a raise.

    Ported hydration: when the row pins a revision, the revision's payload (html, versions,
    manifest, digests) overlays the serving row — so a reader always sees the content-addressed
    package, not a drifted denormalized copy.
    """
    row = (
        await conn.execute(
            text("SELECT * FROM design_web_publish WHERE workspace_id = :w AND slug = :s"),
            {"w": workspace_id, "s": slug},
        )
    ).first()
    if row is None:
        return None
    publish = _web_publish_from_row(row)
    publish_id = publish.get("publish_id")
    if isinstance(publish_id, str):
        revision = await require_web_publish_revision(
            conn, workspace_id=workspace_id, publish_id=publish_id
        )
        publish.update(
            {
                "html": revision["html"],
                "doc_version": revision["doc_version"],
                "runtime_version": revision["runtime_version"],
                "manifest": revision["manifest"],
                "manifest_digest": revision["manifest_digest"],
                "package_digest": revision["package_digest"],
                "html_digest": revision["html_digest"],
            }
        )
    return publish


async def require_web_publish(conn: AsyncConnection, *, workspace_id: str, slug: str) -> JsonObject:
    """Fetch or raise — the fail-closed read the write paths read back through."""
    publish = await get_web_publish(conn, workspace_id=workspace_id, slug=slug)
    if publish is None:
        raise DesignNotFoundError("web_publish", slug)
    return publish


async def get_web_publish_for_document(
    conn: AsyncConnection, *, workspace_id: str, document_id: str
) -> JsonObject | None:
    """The document's live publish, else its most recently updated one.

    The live (``active``) row comes first because recency alone picks the wrong address after a
    move: ``unpublish_other_slugs`` re-stamps ``updated_at`` on the slugs it retires, so the
    address the document moved FROM is the most recently updated row. When nothing is live
    (everything unpublished), the newest row is still returned, so an unpublished document's
    state keeps reporting ``status: "unpublished"``.
    """
    row = (
        await conn.execute(
            text(
                "SELECT slug FROM design_web_publish"
                " WHERE workspace_id = :w AND document_id = :d"
                " ORDER BY (status = 'active') DESC, updated_at DESC LIMIT 1"
            ),
            {"w": workspace_id, "d": document_id},
        )
    ).first()
    if row is None:
        return None
    return await get_web_publish(conn, workspace_id=workspace_id, slug=row.slug)


async def upsert_web_publish(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    slug: str,
    document_id: str,
    doc_version: int,
    html: str,
    runtime_version: int | None,
    publish_id: str | None = None,
) -> JsonObject:
    """Publish (or republish) ``slug``.

    On an existing row the current html/doc_version/publish_id move into ``previous_*`` (the
    single-step rollback buffer) and the new payload becomes current, status ``active`` — all in
    ONE ``INSERT … ON CONFLICT DO UPDATE``, whose ``SET`` list reads ``design_web_publish.*``
    (the *existing* row) while writing ``excluded.*`` (the new one). A republish can therefore
    never observe a half-swapped row.
    """
    await conn.execute(
        text(
            """
            INSERT INTO design_web_publish (
              workspace_id, slug, document_id, doc_version, html, previous_html,
              previous_doc_version, runtime_version, status, publish_id, previous_publish_id
            )
            VALUES (:w, :s, :doc, :doc_version, :html, NULL, NULL, :runtime, 'active', :p, NULL)
            ON CONFLICT (workspace_id, slug) DO UPDATE SET
              document_id = excluded.document_id,
              doc_version = excluded.doc_version,
              html = excluded.html,
              previous_html = design_web_publish.html,
              previous_doc_version = design_web_publish.doc_version,
              previous_publish_id = design_web_publish.publish_id,
              publish_id = excluded.publish_id,
              runtime_version = excluded.runtime_version,
              status = 'active',
              updated_at = now()
            """
        ),
        {
            "w": workspace_id,
            "s": slug,
            "doc": document_id,
            "doc_version": doc_version,
            "html": html,
            "runtime": runtime_version,
            "p": publish_id,
        },
    )
    # F5: the served site is re-derived from the package that just became current, in this same
    # transaction — so the swap of *pages* is as atomic as the swap of the row itself.
    await materialize_web_publish_pages(
        conn, workspace_id=workspace_id, slug=slug, publish_id=publish_id
    )
    return await require_web_publish(conn, workspace_id=workspace_id, slug=slug)


async def set_web_publish_status(
    conn: AsyncConnection, *, workspace_id: str, slug: str, status: str
) -> JsonObject | None:
    """Flip the serving state (unpublish/republish). ``None`` when no such slug — the ported
    ``rowcount == 0`` shape the endpoint turns into its own 404. History is untouched."""
    result = await conn.execute(
        text(
            "UPDATE design_web_publish SET status = CAST(:status AS design_publish_status),"
            " updated_at = now() WHERE workspace_id = :w AND slug = :s"
        ),
        {"status": status, "w": workspace_id, "s": slug},
    )
    if result.rowcount == 0:
        return None
    return await get_web_publish(conn, workspace_id=workspace_id, slug=slug)


async def unpublish_other_slugs(
    conn: AsyncConnection, *, workspace_id: str, document_id: str, keep_slug: str
) -> list[str]:
    """Unpublish every OTHER live slug of ``document_id`` and return them, sorted.

    A document lives at one address: republishing it under a new slug is a MOVE, so the address
    it moved from stops serving (the page origin serves only ``active`` rows, so it 404s). The
    same status ``unpublish`` assigns; history and the revisions are untouched.
    """
    rows = await conn.execute(
        text(
            "UPDATE design_web_publish SET status = 'unpublished', updated_at = now()"
            " WHERE workspace_id = :w AND document_id = :d AND slug <> :keep"
            " AND status = 'active' RETURNING slug"
        ),
        {"w": workspace_id, "d": document_id, "keep": keep_slug},
    )
    return sorted(str(row[0]) for row in rows)


async def rollback_web_publish(
    conn: AsyncConnection, *, workspace_id: str, slug: str
) -> JsonObject | str:
    """Swap current and previous html/doc_version/publish_id (a one-step undo) and re-activate.

    Returns the updated publish dict, or the ported string marker ``'not_found'`` (unknown slug)
    / ``'no_previous'`` (nothing to roll back to). A single UPDATE evaluates every SET expression
    against the ORIGINAL row, so reading and writing html/previous_html in one statement swaps
    them atomically — the ported guarantee, preserved verbatim.

    F5: the served *pages* swap with it. The current pages are re-materialized from the revision
    that just swapped in, in this same transaction, so a route the newer revision had dropped
    comes back with the older revision's own html — never a stale row the newer publish left.
    """
    row = (
        await conn.execute(
            text(
                "SELECT previous_html FROM design_web_publish"
                " WHERE workspace_id = :w AND slug = :s FOR UPDATE"
            ),
            {"w": workspace_id, "s": slug},
        )
    ).first()
    if row is None:
        return "not_found"
    if row.previous_html is None:
        return "no_previous"
    swapped_in = (
        await conn.execute(
            text(
                """
            UPDATE design_web_publish SET
              html = previous_html,
              doc_version = previous_doc_version,
              previous_html = html,
              previous_doc_version = doc_version,
              publish_id = previous_publish_id,
              previous_publish_id = publish_id,
              status = 'active',
              updated_at = now()
            WHERE workspace_id = :w AND slug = :s
            RETURNING publish_id
            """
            ),
            {"w": workspace_id, "s": slug},
        )
    ).scalar()
    # F5: the swapped-in revision's own pages become the served site again — taken from the
    # UPDATE's RETURNING rather than re-read, so it is the id this statement actually wrote.
    await materialize_web_publish_pages(
        conn, workspace_id=workspace_id, slug=slug, publish_id=swapped_in
    )
    return await require_web_publish(conn, workspace_id=workspace_id, slug=slug)


# --- delivery constants shared by the page origin and the design API's publish package -------
# Custom-domain publishing (design 2026-09-17 §5.2, §6.2). One home so the served header and the
# embedded meta can never drift: the origin sends DELIVERY_CSP_HEADER; build_publish_package
# embeds DELIVERY_CSP_META (frame-ancestors is ignored inside a meta CSP by spec).

DELIVERY_CSP_META = (
    "default-src 'none'; script-src 'self' 'unsafe-inline' data:; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; "
    "connect-src 'none'; object-src 'none'; worker-src 'none'; frame-src 'self' data: blob:; "
    "base-uri 'none'; form-action 'none'"
)
DELIVERY_CSP_HEADER = DELIVERY_CSP_META + "; frame-ancestors 'self'"


#: A Puck SITE publish (Wave 2 Contract 3). Published sites are script-free, so script is refused
#: outright; styles may be same-origin or inline (the theme and the clones' captured CSS are
#: inline); images and fonts same-origin or data:; media same-origin. Chosen per publish by the
#: manifest's ``delivery`` field (``manifest_delivery``).
SITE_DELIVERY_CSP_META = (
    "default-src 'none'; script-src 'none'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data:; media-src 'self'; connect-src 'none'; "
    "form-action 'none'; base-uri 'none'"
)
SITE_DELIVERY_CSP_HEADER = SITE_DELIVERY_CSP_META + "; frame-ancestors 'self'"


#: A LIVE Puck site publish (publishing live sites, phase 1): the page runs its own files from
#: /p-assets (the site runtime, the host shims, the agent section modules) and the one inline import
#: map, allowed by its hash. Nothing else runs; it may connect only to its own origin; it frames and
#: submits nothing (forms, embeds and snippets come in later phases and widen this per site).
SITE_LIVE_DELIVERY = "site_live"
_HASH_TOKEN = re.compile(r"^sha256-[A-Za-z0-9+/]{43}=$")


def site_live_csp(script_hashes: Sequence[str], *, meta: bool) -> str:
    hashes = "".join(
        f" '{token}'" for token in sorted(set(script_hashes)) if _HASH_TOKEN.fullmatch(token)
    )
    policy = (
        f"default-src 'none'; script-src 'self'{hashes}; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self' data:; media-src 'self'; connect-src 'self'; "
        "object-src 'none'; worker-src 'none'; frame-src 'none'; form-action 'none'; "
        "base-uri 'none'"
    )
    return policy if meta else policy + "; frame-ancestors 'self'"


def delivery_csp(
    *, meta: bool = False, delivery: str = "web", script_hashes: Sequence[str] = ()
) -> str:
    if delivery == SITE_LIVE_DELIVERY:
        return site_live_csp(script_hashes, meta=meta)
    if delivery == "site":
        return SITE_DELIVERY_CSP_META if meta else SITE_DELIVERY_CSP_HEADER
    return DELIVERY_CSP_META if meta else DELIVERY_CSP_HEADER


def manifest_delivery(manifest: object) -> str:
    """Which policy a publish is served under, from its manifest's ``delivery`` field."""
    if isinstance(manifest, dict) and manifest.get("delivery") in ("site", SITE_LIVE_DELIVERY):
        return str(manifest["delivery"])
    return "web"


def live_script_hashes(manifest: object) -> tuple[str, ...]:
    """The inline-script hashes a live site page is allowed, from ``manifest["live"]``.

    Only well-formed ``sha256-<base64>`` tokens survive, so a manifest can never smuggle another
    CSP source (``'unsafe-eval'``, a host) into the policy through this list.
    """
    live = manifest.get("live") if isinstance(manifest, dict) else None
    hashes = live.get("script_hashes") if isinstance(live, dict) else None
    if not isinstance(hashes, list | tuple):
        return ()
    return tuple(h for h in hashes if isinstance(h, str) and _HASH_TOKEN.fullmatch(h))


PUBLISH_ASSET_EXTENSIONS: tuple[str, ...] = ("js", "css", "html")
PUBLISH_ASSET_MEDIA_TYPES: dict[str, str] = {
    "js": "text/javascript; charset=utf-8",
    "css": "text/css; charset=utf-8",
    "html": "text/html; charset=utf-8",
}


class PublishAssetMismatch(ValueError):
    """The bytes behind a publish-asset URL do not match what the URL promises."""


def check_publish_asset(*, data: bytes, media_type: str, digest: str, extension: str) -> str:
    """Integrity-check one immutable publish asset; returns the media type to serve.

    The URL's extension must agree with the media type recorded on the blob's ``artifact`` row, and
    the bytes must hash to the digest in the URL — so ``/{digest}.css`` can never serve JavaScript.
    Re-homed from ``lumen_api.web_export.resolve_publish_asset`` so the page origin (which may not
    import ``lumen_api``) and the design API share one rule.
    """
    expected = PUBLISH_ASSET_MEDIA_TYPES.get(extension)
    if expected is None:
        raise PublishAssetMismatch("publish asset media type does not match its URL")
    if hashlib.sha256(data).hexdigest() != digest:
        raise PublishAssetMismatch("publish asset failed its integrity check")
    if media_type != expected:
        raise PublishAssetMismatch("publish asset media type does not match its URL")
    return expected
