"""Durable custody for what a website ingestion actually saw (clone-fidelity F0.1).

``capture_website`` builds a :class:`~lumen_ingestion.capture.snapshot.SiteSnapshot` per page —
the post-JS HTML, every stylesheet it fetched, and (on the rendered tier) a full-page screenshot
— and until this module existed the pipeline handed it to the evidence builder and dropped it.
``BrandEvidence`` is a SUMMARY: colors, fonts, a handful of measurements. A section-level clone
needs the markup and the CSS the brand actually ships, and a screenshot-vs-source review gate
needs the picture, so both are now kept.

**Bytes go through the design byte seam**, content-addressed under
``{workspace}/design/{sha256}`` with an ``artifact`` row apiece and
``source_key = "design_site_snapshot"``. Re-ingesting an unchanged site therefore costs one row
per page and no bytes at all — the digests collide with the blobs already stored. Nothing here
reformats what it stores: the html is the html as captured, each stylesheet is the text as
fetched, the screenshot is the PNG the browser produced.

**Rows go through the design DAL** (:mod:`clue_design.site_snapshots`), one row per
``(job, page)``, keyed on an id derived from that pair so a re-offered job converges on the rows
its earlier attempt wrote.

Two read surfaces, one implementation: :func:`load_site_snapshot` for a caller that already owns
a connection (the async DAL-side consumer — phase F2's section harvester), and
:func:`read_site_snapshot` for the design API's synchronous world, which reaches Postgres
through the same one-call/one-transaction bridge every other design store uses.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any, Sequence

from clue_design import site_snapshots as dal
from clue_design.storage import SOURCE_KEY_SITE_SNAPSHOT, read_design_bytes, register_design_bytes
from clue_storage import StorageBackend
from lumen_api.design_store import DesignStoreBridge

from .capture.geometry import captured_font_context
from .sections.bands import (
    SNAPSHOT_META_BANDS_KEY,
    SNAPSHOT_META_SKIPPED_KEY,
    SNAPSHOT_META_TRUNCATED_KEY,
    bands_for_meta,
    skipped_for_meta,
)

#: ``source_key`` on the ``artifact`` rows this seam writes (observability, not identity).
SITE_SNAPSHOT_SOURCE_KEY = SOURCE_KEY_SITE_SNAPSHOT

#: The loud diagnostic a failed persistence leaves on the job. Snapshot custody is additive: a
#: capture that produced real evidence must not be thrown away because the blob store hiccuped,
#: and a hiccup must not pass in silence either.
SNAPSHOT_PERSIST_FAILED_CODE = "LUMI0512"

_HTML_MEDIA_TYPE = "text/html; charset=utf-8"
_CSS_MEDIA_TYPE = "text/css; charset=utf-8"
_DEFAULT_SCREENSHOT_MEDIA_TYPE = "image/png"


@dataclass(frozen=True)
class SiteSnapshotRef:
    """What one persisted page IS, in digests — the handle later phases read rows and bytes by."""

    snapshot_id: str
    page_url: str
    page_index: int
    html_digest: str
    stylesheet_digests: tuple[str, ...]
    screenshot_digest: str | None

    def as_job_ref(self) -> dict[str, Any]:
        """The bounded shape recorded on the ingestion job's evidence payload."""
        return {
            "snapshot_id": self.snapshot_id,
            "page_url": self.page_url,
            "html_digest": self.html_digest,
            "screenshot_digest": self.screenshot_digest,
        }


@dataclass(frozen=True)
class LoadedStylesheet:
    url: str
    text: str
    raw_text: str | None = None
    source_order: tuple[int, ...] | None = None
    media: str | None = None
    disabled: bool = False
    imported_from: str | None = None


@dataclass(frozen=True)
class LoadedSiteSnapshot:
    """One captured page, bytes and all, read back out of durable custody."""

    snapshot_id: str
    page_url: str
    page_index: int
    html: str
    stylesheets: tuple[LoadedStylesheet, ...]
    screenshot: bytes | None
    viewport_width: int | None
    captured_at: str
    meta: dict[str, Any]


def site_snapshot_id(job_id: str, page_url: str) -> str:
    """The id of one captured page: ``snap_<sha256(job_id, page_url)[:16]>``.

    Derived from exactly the pair the table's UNIQUE constraint protects, so the id and the
    constraint cannot disagree about what "the same page of the same job" means — which is what
    lets a re-offered job re-record its pages onto the rows it already wrote.
    """
    digest = hashlib.sha256(f"{job_id}\x00{page_url}".encode("utf-8")).hexdigest()
    return f"snap_{digest[:16]}"


def persist_site_snapshots(
    snapshots: Sequence[Any],
    *,
    workspace_id: str,
    job_id: str,
    storage: StorageBackend,
) -> list[SiteSnapshotRef]:
    """Give one job's captured pages durable custody; return a ref per page, in capture order.

    ONE bridged transaction for the whole job (the O5 rule): the blobs and the rows that cite
    them are one logical operation, and a committed row naming bytes that never landed would be
    a dangling evidence reference nothing downstream could tell from a real one.

    ``snapshots[0]`` is the entry page (``page_index`` 0); the rest follow in the order the
    capture produced them. A page whose url repeats within the same job is recorded once — the
    id and the constraint both key on ``(job, page_url)``, so a duplicate is the same page, and
    the later capture of it wins.
    """

    async def _persist(conn: Any) -> list[SiteSnapshotRef]:
        refs: list[SiteSnapshotRef] = []
        for page_index, snapshot in enumerate(snapshots):
            refs.append(
                await _persist_one(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    job_id=job_id,
                    page_index=page_index,
                    snapshot=snapshot,
                )
            )
        return refs

    return DesignStoreBridge(workspace_id)._run(_persist)


async def _persist_one(
    conn: Any,
    storage: StorageBackend,
    *,
    workspace_id: str,
    job_id: str,
    page_index: int,
    snapshot: Any,
) -> SiteSnapshotRef:
    page_url = snapshot.requested_url
    html_bytes = snapshot.html.encode("utf-8")
    html_digest = _digest(html_bytes)
    await register_design_bytes(
        conn,
        storage,
        workspace_id=workspace_id,
        data=html_bytes,
        media_type=_HTML_MEDIA_TYPE,
        source_key=SITE_SNAPSHOT_SOURCE_KEY,
    )

    stylesheets: list[dict[str, Any]] = []
    for sheet in snapshot.stylesheets:
        sheet_bytes = sheet.text.encode("utf-8")
        sheet_digest = _digest(sheet_bytes)
        await register_design_bytes(
            conn,
            storage,
            workspace_id=workspace_id,
            data=sheet_bytes,
            media_type=_CSS_MEDIA_TYPE,
            source_key=SITE_SNAPSHOT_SOURCE_KEY,
        )
        entry = {"url": sheet.url, "digest": sheet_digest, "byte_length": len(sheet_bytes)}
        raw_text = getattr(sheet, "raw_text", None)
        if raw_text is not None:
            raw_bytes = raw_text.encode("utf-8")
            await register_design_bytes(
                conn,
                storage,
                workspace_id=workspace_id,
                data=raw_bytes,
                media_type=_CSS_MEDIA_TYPE,
                source_key=SITE_SNAPSHOT_SOURCE_KEY,
            )
            entry["raw_digest"] = _digest(raw_bytes)
        for name in ("source_order", "media", "disabled", "imported_from"):
            value = getattr(sheet, name, None)
            if value is not None and value is not False:
                entry[name] = value
        stylesheets.append(entry)

    screenshot = _screenshot_download(snapshot)
    screenshot_digest: str | None = None
    if screenshot is not None:
        shot_bytes = base64.b64decode(screenshot.bytes_b64)
        screenshot_digest = _digest(shot_bytes)
        await register_design_bytes(
            conn,
            storage,
            workspace_id=workspace_id,
            data=shot_bytes,
            media_type=screenshot.content_type or _DEFAULT_SCREENSHOT_MEDIA_TYPE,
            source_key=SITE_SNAPSHOT_SOURCE_KEY,
        )

    # Preserve every successful source download, even if a section cannot yet
    # mint. Otherwise repair requires another network capture, and video (which
    # deliberately bypasses the image engine) has no durable custody at all.
    assets: list[dict[str, Any]] = []
    for download in getattr(snapshot, "downloads", None) or []:
        if download.kind == "screenshot":
            continue
        data = base64.b64decode(download.bytes_b64, validate=True)
        digest = _digest(data)
        if digest != download.sha256:
            raise ValueError(f"capture asset digest mismatch: {download.url}")
        media_type = download.content_type or "application/octet-stream"
        await register_design_bytes(
            conn,
            storage,
            workspace_id=workspace_id,
            data=data,
            media_type=media_type,
            source_key=SITE_SNAPSHOT_SOURCE_KEY,
        )
        assets.append(
            {
                "url": download.url,
                "digest": digest,
                "kind": download.kind,
                "content_type": media_type,
                "byte_length": len(data),
                "origin": download.origin,
                "dark_scheme": download.dark_scheme,
            }
        )
    meta = _meta(snapshot)
    from .capture.page_plan import motion_inventory

    meta["motion"] = motion_inventory(snapshot)
    meta["assets"] = assets
    meta["diagnostics"] = list(getattr(snapshot, "diagnostics", None) or [])

    snapshot_id = site_snapshot_id(job_id, page_url)
    await dal.upsert_site_snapshot(
        conn,
        workspace_id=workspace_id,
        snapshot_id=snapshot_id,
        job_id=job_id,
        page_url=page_url,
        page_index=page_index,
        html_digest=html_digest,
        stylesheets=stylesheets,
        screenshot_digest=screenshot_digest,
        viewport_width=_viewport_width(snapshot),
        captured_at=snapshot.fetched_at,
        meta=meta,
    )
    return SiteSnapshotRef(
        snapshot_id=snapshot_id,
        page_url=page_url,
        page_index=page_index,
        html_digest=html_digest,
        stylesheet_digests=tuple(sheet["digest"] for sheet in stylesheets),
        screenshot_digest=screenshot_digest,
    )


async def load_site_snapshot(
    conn: Any, storage: StorageBackend, snapshot_id: str, *, workspace_id: str
) -> LoadedSiteSnapshot:
    """One captured page with its bytes — html text, ordered stylesheet texts, screenshot or None.

    ``workspace_id`` is required rather than read off the row: an unscoped read by a
    content-derived id is exactly the shape that leaks existence across tenants, and every other
    design read in this codebase is fail-closed on the caller's workspace.
    """
    row = await dal.get_site_snapshot(conn, workspace_id=workspace_id, snapshot_id=snapshot_id)
    html = (
        await read_design_bytes(conn, storage, workspace_id=workspace_id, sha256=row["html_digest"])
    ).decode("utf-8", errors="replace")

    stylesheets: list[LoadedStylesheet] = []
    for sheet in row["stylesheets"] or []:
        data = await read_design_bytes(
            conn, storage, workspace_id=workspace_id, sha256=sheet["digest"]
        )
        raw_text = None
        if sheet.get("raw_digest"):
            raw_text = (
                await read_design_bytes(
                    conn, storage, workspace_id=workspace_id, sha256=sheet["raw_digest"]
                )
            ).decode("utf-8", errors="replace")
        stylesheets.append(
            LoadedStylesheet(
                url=sheet["url"],
                text=data.decode("utf-8", errors="replace"),
                raw_text=raw_text,
                source_order=tuple(sheet["source_order"])
                if sheet.get("source_order") is not None
                else None,
                media=sheet.get("media"),
                disabled=bool(sheet.get("disabled")),
                imported_from=sheet.get("imported_from"),
            )
        )

    screenshot: bytes | None = None
    if row["screenshot_digest"]:
        screenshot = await read_design_bytes(
            conn, storage, workspace_id=workspace_id, sha256=row["screenshot_digest"]
        )

    return LoadedSiteSnapshot(
        snapshot_id=row["snapshot_id"],
        page_url=row["page_url"],
        page_index=row["page_index"],
        html=html,
        stylesheets=tuple(stylesheets),
        screenshot=screenshot,
        viewport_width=row["viewport_width"],
        captured_at=row["captured_at"],
        meta=row["meta"] or {},
    )


def read_site_snapshot(
    storage: StorageBackend, *, workspace_id: str, snapshot_id: str
) -> LoadedSiteSnapshot:
    """:func:`load_site_snapshot` for the design API's synchronous world (one bridged call)."""
    return DesignStoreBridge(workspace_id)._run(
        lambda conn: load_site_snapshot(conn, storage, snapshot_id, workspace_id=workspace_id)
    )


def list_site_snapshot_refs(*, workspace_id: str, job_id: str) -> list[SiteSnapshotRef]:
    """Every page one job captured, in capture order — refs only, no bytes read."""

    async def _list(conn: Any) -> list[SiteSnapshotRef]:
        rows = await dal.list_site_snapshots_for_job(conn, workspace_id=workspace_id, job_id=job_id)
        return [
            SiteSnapshotRef(
                snapshot_id=row["snapshot_id"],
                page_url=row["page_url"],
                page_index=row["page_index"],
                html_digest=row["html_digest"],
                stylesheet_digests=tuple(sheet["digest"] for sheet in (row["stylesheets"] or [])),
                screenshot_digest=row["screenshot_digest"],
            )
            for row in rows
        ]

    return DesignStoreBridge(workspace_id)._run(_list)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _screenshot_download(snapshot: Any) -> Any | None:
    for download in getattr(snapshot, "downloads", None) or []:
        if getattr(download, "kind", None) == "screenshot":
            return download
    return None


def _viewport_width(snapshot: Any) -> int | None:
    """The width the page was measured at, when the capture measured one.

    Read off the rendered tier's geometry harvest rather than the browser launch constant, so
    the column records what the page actually saw (``innerWidth``) and stays honestly NULL for
    the static tier, which never opened a viewport at all.
    """
    geometry = getattr(snapshot, "geometry", None)
    if not isinstance(geometry, dict):
        return None
    try:
        width = int(geometry.get("viewport"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return width if width > 0 else None


def _meta(snapshot: Any) -> dict[str, Any]:
    """The row's ``meta_json``: the page's own meta NESTED, plus the capture's own facts.

    Nested rather than merged because the page's meta keys are whatever the site put in its
    ``<head>`` — merging our keys in beside them would let a site's ``og:`` block decide what
    ``tier`` or ``final_url`` mean here.

    The MEASURED BAND SEQUENCE rides here too (clone-fidelity F2.1). The rest of the geometry
    harvest is a color-and-shape finding that the evidence builder already digests into the kit;
    the bands are the only part phase F2 needs back verbatim, because a section's role and its
    screenshot crop are read off them long after the browser is gone. Bounded by the probe's own
    section cap, and ``[]`` for a static-tier capture that measured nothing.
    """
    return {
        "meta": dict(getattr(snapshot, "meta", None) or {}),
        "tier": getattr(snapshot, "tier", None),
        "font_context": captured_font_context(getattr(snapshot, "geometry", None)),
        "requested_url": getattr(snapshot, "requested_url", None),
        "final_url": getattr(snapshot, "final_url", None),
        "fetched_at": getattr(snapshot, "fetched_at", None),
        SNAPSHOT_META_BANDS_KEY: bands_for_meta(getattr(snapshot, "geometry", None)),
        SNAPSHOT_META_SKIPPED_KEY: skipped_for_meta(getattr(snapshot, "geometry", None)),
        SNAPSHOT_META_TRUNCATED_KEY: bool(
            (getattr(snapshot, "geometry", None) or {}).get("truncated")
            if isinstance(getattr(snapshot, "geometry", None), dict)
            else False
        ),
    }
