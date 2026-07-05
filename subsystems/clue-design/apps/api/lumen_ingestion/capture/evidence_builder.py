"""``CaptureOutcome`` (+ its ParsedSite) → ``BrandEvidence``, ingesting fonts,
logos, images, and screenshots into the asset store.

``build_evidence`` is sync (it owns the event loop) but ingests all assets
concurrently: ``ingest_asset`` is a blocking subprocess, so each call runs in a
thread under a ``Semaphore(4)`` and all of them are gathered inside a single
``asyncio.run``.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
from dataclasses import dataclass
from urllib.parse import urlparse

from ..evidence import (
    BrandEvidence,
    ColorEvidence,
    EvidencePointer,
    FontEvidence,
    FontFaceEvidence,
    ImageEvidence,
    LogoEvidence,
    NarrativeEvidence,
    TypeSample,
)
from .parse import ParsedAsset, ParsedSite, parse_site

INGEST_CONCURRENCY = 4


@dataclass
class _AssetJob:
    url: str | None
    sha256: str
    body: bytes
    kind: str  # "font" | "image" (ingest kind hint; images/logos left to sniff)
    filename: str
    content_type: str | None


def _pointer(locator: str) -> EvidencePointer:
    return EvidencePointer(source="website", locator=locator)


def _filename_from_url(url: str | None, fallback: str) -> str:
    if not url:
        return fallback
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1]
    return name or fallback


def build_evidence(outcome, *, core, store_root: str, reporter) -> BrandEvidence:
    snapshot = outcome.snapshot
    parsed: ParsedSite = parse_site(snapshot)

    reporter("Capturing your colors…", 0.65)
    colors = [
        ColorEvidence(
            value=c.value,
            weight=c.weight,
            theme=c.theme,  # type: ignore[arg-type]
            role_hints=c.role_hints,
            name=c.name,
            pointer=_pointer(c.locator),
        )
        for c in parsed.colors
    ]

    reporter("Matching your typography…", 0.75)
    type_samples = [
        TypeSample(
            label=t.label,
            family=t.family,
            weight=t.weight,
            size_px=t.size_px,
            line_height=t.line_height,
            letter_spacing=t.letter_spacing,
            pointer=_pointer(t.locator),
        )
        for t in parsed.type_samples
    ]

    # --- resolve download bytes for asset ingest ---
    sha_bytes: dict[str, bytes] = {}
    sha_ct: dict[str, str | None] = {}
    for entry in snapshot.downloads:
        sha_bytes[entry.sha256] = base64.b64decode(entry.bytes_b64)
        sha_ct[entry.sha256] = entry.content_type

    # Inline SVG logos captured during parse have no download; register bytes now.
    inline_svgs = getattr(parsed, "_inline_svgs", [])
    inline_by_index: list[tuple[str, bytes]] = []
    for markup in inline_svgs:
        body = markup.encode("utf-8")
        sha = hashlib.sha256(body).hexdigest()
        sha_bytes[sha] = body
        sha_ct[sha] = "image/svg+xml"
        inline_by_index.append((sha, body))

    jobs: dict[str, _AssetJob] = {}

    def queue(sha: str | None, url: str | None, kind: str, default_name: str) -> str | None:
        if not sha or sha not in sha_bytes:
            return None
        if sha not in jobs:
            jobs[sha] = _AssetJob(
                url=url,
                sha256=sha,
                body=sha_bytes[sha],
                kind=kind,
                filename=_filename_from_url(url, default_name),
                content_type=sha_ct.get(sha),
            )
        return f"asset_ing_{sha[:16]}"

    # Fonts (from @font-face faces with downloaded files).
    fonts: list[FontEvidence] = []
    for font in parsed.fonts:
        faces: list[FontFaceEvidence] = []
        for face in font.faces:
            face_sha = None
            asset_id = None
            if face.source_url:
                face_sha = _sha_for_url(snapshot, face.source_url)
                if face_sha:
                    asset_id = queue(
                        face_sha,
                        face.source_url,
                        "font",
                        f"{font.family}.{face.format or 'woff2'}",
                    )
            faces.append(
                FontFaceEvidence(
                    weight=face.weight,
                    style=face.style,
                    asset_id=asset_id,
                    source_url=face.source_url,
                    format=face.format,
                )
            )
        fonts.append(
            FontEvidence(
                family=font.family,
                role_hint=font.role_hint,  # type: ignore[arg-type]
                faces=faces,
                fallback_stack=font.fallback_stack,
                license_hint=font.license_hint,
                pointer=_pointer(font.locator),
            )
        )

    # Logos.
    logos: list[LogoEvidence] = []
    inline_cursor = 0
    for asset in parsed.logos:
        sha = asset.sha256
        url = asset.source_url
        if sha is None and url is None and inline_cursor < len(inline_by_index):
            # inline SVG logo
            sha, _ = inline_by_index[inline_cursor]
            inline_cursor += 1
        asset_id = queue(sha, url, "image", _filename_from_url(url, "logo.svg"))
        if asset_id is None:
            continue
        logos.append(
            LogoEvidence(
                asset_id=asset_id,
                usage_hint=asset.usage_hint,  # type: ignore[arg-type]
                width=float(asset.width) if asset.width else None,
                height=float(asset.height) if asset.height else None,
                background_hint=asset.background_hint,
                pointer=_pointer(asset.locator),
            )
        )

    # Images.
    images: list[ImageEvidence] = []
    for asset in parsed.images:
        asset_id = queue(
            asset.sha256, asset.source_url, "image", _filename_from_url(asset.source_url, "image")
        )
        if asset_id is None:
            continue
        images.append(
            ImageEvidence(
                asset_id=asset_id,
                width=asset.width,
                height=asset.height,
                kind_hint=asset.kind_hint,  # type: ignore[arg-type]
                pointer=_pointer(asset.locator),
            )
        )

    # Screenshots (rendered tier).
    screenshots: list[str] = []
    for entry in snapshot.downloads:
        if entry.kind == "screenshot":
            asset_id = queue(entry.sha256, entry.url, "image", "screenshot.png")
            if asset_id:
                screenshots.append(asset_id)

    # --- ingest all queued assets concurrently ---
    if jobs:
        _run_ingest(list(jobs.values()), core=core, store_root=store_root, snapshot=snapshot)

    narrative = NarrativeEvidence(
        brand_name=parsed.narrative.brand_name,
        url=parsed.narrative.url,
        tagline=parsed.narrative.tagline,
        summary_facts=parsed.narrative.summary_facts,
        text_excerpt=parsed.narrative.text_excerpt,
    )

    source = {
        "kind": "website",
        "url": snapshot.requested_url,
        "captured_at": snapshot.fetched_at,
        "confidence": 0.7,
    }

    return BrandEvidence(
        source=source,
        colors=colors,
        type_samples=type_samples,
        fonts=fonts,
        logos=logos,
        images=images,
        screenshots=screenshots,
        narrative=narrative,
    )


def _sha_for_url(snapshot, url: str) -> str | None:
    for entry in snapshot.downloads:
        if entry.url == url:
            return entry.sha256
    return None


def _run_ingest(jobs: list[_AssetJob], *, core, store_root: str, snapshot) -> None:
    async def _drive() -> None:
        semaphore = asyncio.Semaphore(INGEST_CONCURRENCY)

        async def _one(job: _AssetJob) -> None:
            async with semaphore:
                await asyncio.to_thread(_ingest_one, job, core, store_root, snapshot)

        await asyncio.gather(*(_one(job) for job in jobs))

    asyncio.run(_drive())


def _ingest_one(job: _AssetJob, core, store_root: str, snapshot) -> None:
    asset_id = f"asset_ing_{job.sha256[:16]}"
    # Content-addressed id → idempotent: the store dedupes bytes by digest, so
    # re-ingesting the same content is a no-op that returns the same record.
    core.ingest_asset(
        store_root=store_root,
        bytes_base64=base64.b64encode(job.body).decode("ascii"),
        asset_id=asset_id,
        label=job.filename,
        declared_mime_type=job.content_type,
        filename=job.filename,
        kind="font" if job.kind == "font" else None,
        provenance={
            "created_by": "lumen_ingestion",
            "created_at": snapshot.fetched_at,
            "source_label": "website",
            "confidence": 0.7,
            "notes": [],
        },
        source={"kind": "website", "url": job.url, "captured_at": snapshot.fetched_at}
        if job.url
        else {"kind": "manual", "label": job.filename},
        tags=["brand-ingestion", "font" if job.kind == "font" else "image"],
        max_bytes=15 * 1024 * 1024,
        raise_on_error=False,
    )
