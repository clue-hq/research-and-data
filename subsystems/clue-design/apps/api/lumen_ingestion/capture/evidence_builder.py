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
from .geometry import parse_geometry
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


#: How many characters of the digest ride in a stored filename. Twelve is enough to be
#: unambiguous within one capture while leaving the original basename readable.
_SLURP_SHA_CHARS = 12


def _stored_filename(sha256: str, url: str | None, fallback: str) -> str:
    """``slurp-<sha12>-<original basename>`` — the rehosted asset's origin story, readable.

    Every asset a capture stores is a REHOST of something a page referenced, and a human
    opening the asset library should be able to see that at a glance: where it came from
    (``slurp-``), which exact bytes it is (the digest prefix, matching the content-addressed
    ``asset_ing_<sha16>`` id), and what the site called it. The source URL itself is already
    carried by the asset's ``source``/provenance, so the filename does not have to encode it.

    Asset-id minting is deliberately untouched — the id stays ``asset_ing_<sha16>``.
    """
    basename = _filename_from_url(url, fallback) or fallback
    return f"slurp-{sha256[:_SLURP_SHA_CHARS]}-{basename}"


def _fetch_failure_reasons(snapshot) -> dict[str, str]:
    """``url -> why it never arrived``, read off the capture's own fetch diagnostics.

    ``net.py`` stamps ``url``/``reason`` as their own keys on every LUMI0502/LUMI0503 exactly
    so this join does not have to parse a human sentence.
    """
    reasons: dict[str, str] = {}
    for diagnostic in getattr(snapshot, "diagnostics", None) or []:
        if not isinstance(diagnostic, dict):
            continue
        url = diagnostic.get("url")
        reason = diagnostic.get("reason")
        if isinstance(url, str) and isinstance(reason, str) and url not in reasons:
            reasons[url] = reason
    return reasons


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

    # Inline SVG logos have no download of their own. `_ladder_logos` registers
    # the bytes for whichever one wins a slot — repaired, so the camelCase
    # attribute names a strict renderer needs survive the HTML round trip.
    jobs: dict[str, _AssetJob] = {}
    #: Everything the page referenced that we could not store, with the reason. This list is
    #: the honest replacement for the old silent `return None` — see `_drop_diagnostics`.
    drops: list[tuple[str, str, str]] = []
    fetch_reasons = _fetch_failure_reasons(snapshot)

    def queue(
        sha: str | None,
        url: str | None,
        kind: str,
        default_name: str,
        *,
        context: str = "asset",
    ) -> str | None:
        """Register an asset for ingest, or say out loud why it could not be.

        The ``None`` return used to be a silent drop — every caller answered it with
        ``continue`` — which is exactly how a scored-but-never-fetched logo disappeared
        without a word. It still returns ``None`` (the caller genuinely has no asset id to
        use), but the drop is now recorded and reported.
        """
        if not sha or sha not in sha_bytes:
            drops.append(
                (
                    url or default_name,
                    fetch_reasons.get(url or "", "no bytes were captured for it"),
                    context,
                )
            )
            return None
        if sha not in jobs:
            jobs[sha] = _AssetJob(
                url=url,
                sha256=sha,
                body=sha_bytes[sha],
                kind=kind,
                filename=_stored_filename(sha, url, default_name),
                content_type=sha_ct.get(sha),
            )
        return f"asset_ing_{sha[:16]}"

    # Fonts (from @font-face faces with downloaded files).
    fonts: list[FontEvidence] = []
    uncustodied_faces: list[str] = []
    face_failures: list[dict] = []
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
                        context=f"@font-face {font.family} {face.weight or 400}",
                    )
            if face.source_url and asset_id is None:
                # PER FACE, with the reason (clone-fidelity F0.2). LUMI0231 below is the
                # family-level summary a human skims; this is the line that says which file
                # and why, which is what anyone actually debugging a fallback needs.
                face_failures.append(
                    {
                        "code": "LUMI0516",
                        "severity": "warning",
                        "message": (
                            f"font file not retrieved for {font.family} "
                            f"{face.weight or 400} {face.style or 'normal'} "
                            f"({face.source_url}): "
                            + fetch_reasons.get(
                                face.source_url, "no bytes were captured for it"
                            )
                        ),
                        "url": face.source_url,
                        "family": font.family,
                        "reason": fetch_reasons.get(
                            face.source_url, "no bytes were captured for it"
                        ),
                    }
                )
                # A face declared by the site whose bytes we do not hold. The
                # kit will carry the URL and no asset, the renderer will have
                # nothing to load, and the ad will paint in Inter (LUMS0100).
                # That used to happen in total silence — LUMI0230 only fires
                # when a family has NO faces at all, not when every face is
                # byte-less — so say it plainly instead.
                uncustodied_faces.append(f"{font.family} ({face.source_url})")
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

    # Logos. The ladder — not ``parsed.logos`` — decides which asset fills which
    # slot. ``parse`` still owns the logo/image split (it is what keeps a logo
    # out of ``parsed.images``); the ladder owns selection, so only one scorer
    # ever picks a slot.
    logos = _ladder_logos(snapshot, sha_bytes, sha_ct, queue, outcome)

    # Images.
    images: list[ImageEvidence] = []
    for asset in parsed.images:
        asset_id = queue(
            asset.sha256,
            asset.source_url,
            "image",
            _filename_from_url(asset.source_url, "image"),
            context=f"image at {asset.locator}",
        )
        if asset_id is None:
            # Still a `continue` — an ImageEvidence with no asset id would be a lie — but no
            # longer a SILENT one: `queue` recorded the drop and it becomes a LUMI0515.
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
            asset_id = queue(
                entry.sha256, entry.url, "image", "screenshot.png", context="screenshot"
            )
            if asset_id:
                screenshots.append(asset_id)

    # REHOST EVERYTHING ELSE (clone-fidelity F0.2). The evidence above only queues what the
    # KIT references — the chosen renditions, the ladder's logo slots, the faces that made
    # it. The F2 clone rewrites a captured fragment's asset URLs onto OUR store, so every
    # byte the page referenced has to exist there, including the srcset rungs no kit image
    # chose, the mask a stylesheet pulls, and the sprite an inline <svg> points at. They are
    # stored, not narrated: nothing here invents evidence for them.
    for entry in snapshot.downloads:
        queue(
            entry.sha256,
            entry.url,
            "font" if entry.kind == "font" else "image",
            _filename_from_url(entry.url, entry.kind),
            context=f"captured {entry.origin or entry.kind}",
        )

    # --- ingest all queued assets concurrently ---
    ingest_failures: list[dict] = []
    if jobs:
        ingest_failures = _run_ingest(
            list(jobs.values()), core=core, store_root=store_root, snapshot=snapshot
        )

    # Brand geometry (design-brief slice 2): the rendered tier's measurement
    # harvest → number/shadow evidence + the structured shape records slice 3's
    # brief agent reads. A static-tier capture (or a failed probe) carries no
    # harvest, so this contributes nothing and the derived scale stands.
    geometry = parse_geometry(snapshot.geometry, page_url=snapshot.final_url)
    outcome_diagnostics = getattr(outcome, "diagnostics", None)
    if geometry.diagnostics and isinstance(outcome_diagnostics, list):
        outcome_diagnostics.extend(geometry.diagnostics)
    # Whatever `parse_site` skipped — an unreadable color, a font file with no
    # bytes — is only useful if a human sees it, and `ParsedSite.diagnostics`
    # has no other reader. Forward it onto the outcome, which the pipeline
    # concatenates into the published kit's diagnostics.
    if parsed.diagnostics and isinstance(outcome_diagnostics, list):
        outcome_diagnostics.extend(parsed.diagnostics)
    if uncustodied_faces and isinstance(outcome_diagnostics, list):
        outcome_diagnostics.append(
            {
                "code": "LUMI0231",
                "severity": "warning",
                "message": (
                    "font files declared but not stored, so these faces cannot "
                    "paint and text will fall back: "
                    + ", ".join(uncustodied_faces[:6])
                ),
            }
        )
    # Honest-partial, never silent-partial: every reference we could not store and every
    # ingest that refused is said out loud, and the ingestion still completes.
    if isinstance(outcome_diagnostics, list):
        outcome_diagnostics.extend(face_failures)
        outcome_diagnostics.extend(_drop_diagnostics(drops))
        outcome_diagnostics.extend(ingest_failures)

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
        numbers=geometry.numbers,
        shadows=geometry.shadows,
        geometry=geometry.evidence(),
        screenshots=screenshots,
        narrative=narrative,
    )


def _sha_for_url(snapshot, url: str) -> str | None:
    for entry in snapshot.downloads:
        if entry.url == url:
            return entry.sha256
    return None


# The kit's default dark plate, matching what the uploads path stamps on a
# reversed logo. A brand's own dark surface is better when the ladder read one
# off the page, so this is only the floor.
_DEFAULT_DARK_PLATE = "#121212"

# Which kit slot each ladder slot fills, and in what order. `light` must come
# first: `emit.add_logos` groups by usage_hint and takes group[0] for
# `logo.primary`, so a dark-first order would make the reversed mark the kit's
# primary logo.
_SLOT_ORDER = (
    ("light", "primary"),
    ("dark", "primary"),
    ("mark", "mark"),
    ("wordmark", "wordmark"),
)


def _ladder_logos(snapshot, sha_bytes, sha_ct, queue, outcome) -> list[LogoEvidence]:
    """Resolve the logo family off the captured page and emit it as evidence.

    Every candidate the ladder can consider was downloaded by
    ``static._collect_assets``, so a winning slot always has bytes — which is
    what closes the old silent drop (a JSON-LD/og logo the scorer ranked first
    and the builder discarded without a diagnostic because nobody fetched it).
    """
    from .. import logo_ladder

    stylesheets = [(sheet.url, sheet.text) for sheet in snapshot.stylesheets]
    candidates = logo_ladder.harvest(snapshot.html, snapshot.final_url, stylesheets)
    fetched = {
        entry.url: (sha_bytes[entry.sha256], entry.content_type)
        for entry in snapshot.downloads
        if entry.sha256 in sha_bytes
    }
    logo_ladder.attach_bytes(candidates, fetched)

    page_meta = {
        "homepage_url": snapshot.final_url,
        "page_title": snapshot.meta.get("title") or logo_ladder.page_title(snapshot.html),
        "jsonld_org_names": logo_ladder.jsonld_org_names(snapshot.html),
        "tier": snapshot.tier,
    }
    resolution = logo_ladder.resolve(
        candidates, page_meta, logo_ladder.host_of(snapshot.final_url)
    )

    diagnostics = getattr(outcome, "diagnostics", None)
    if resolution.status != "resolved" and isinstance(diagnostics, list):
        # The honest replacement for the silent drop: say why no logo family was
        # accepted, and name the assets a human would choose between.
        diagnostics.append({
            "code": "LUMI0510",
            "severity": "warning",
            "message": (
                f"logo ladder returned {resolution.status}: "
                + "; ".join(resolution.notes[:3])
            ),
            "candidates": [c.summary() for c in resolution.ranked[:5]],
        })

    dark_plate = resolution.theme_surfaces.get("dark_surface") or _DEFAULT_DARK_PLATE

    logos: list[LogoEvidence] = []
    for slot_name, usage_hint in _SLOT_ORDER:
        slot = resolution.slots.get(slot_name)
        if slot is None:
            continue
        sha = hashlib.sha256(slot.body).hexdigest()
        sha_bytes.setdefault(sha, slot.body)
        sha_ct.setdefault(sha, slot.content_type)
        asset_id = queue(
            sha,
            slot.candidate.url,
            "image",
            _filename_from_url(slot.candidate.url, f"logo-{slot_name}.svg"),
        )
        if asset_id is None:  # pragma: no cover - the bytes were just registered
            continue
        reversed_slot = slot_name == "dark"
        logos.append(
            LogoEvidence(
                asset_id=asset_id,
                color_mode_hint=_color_mode(slot, reversed_slot),
                usage_hint=usage_hint,  # type: ignore[arg-type]
                width=float(slot.candidate.width) if slot.candidate.width else None,
                height=float(slot.candidate.height) if slot.candidate.height else None,
                background_hint=dark_plate if reversed_slot else None,
                pointer=_pointer(_ladder_locator(slot_name, slot)),
            )
        )
    return logos


def _color_mode(slot, reversed_slot: bool) -> str:
    if reversed_slot:
        return "reversed"
    # A `currentColor` asset genuinely has one ink and takes it from the page.
    if slot.candidate.appearance.get("verdict") == "adaptive":
        return "one_color"
    return "full_color"


def _ladder_locator(slot_name: str, slot) -> str:
    detail = slot.basis or slot.candidate.lockup
    return (
        f"logo-ladder :: {slot_name} <- {slot.candidate.rung} "
        f"[{slot.provenance}] {detail}"
    )[:400]


def _drop_diagnostics(drops: list[tuple[str, str, str]]) -> list[dict]:
    """One ``LUMI0515`` per asset the page referenced and we could not store.

    Deduped by URL: a rendition referenced from three places is one missing file, not three.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for url, reason, context in drops:
        if url in seen:
            continue
        seen.add(url)
        out.append(
            {
                "code": "LUMI0515",
                "severity": "warning",
                "message": (
                    f"referenced asset not stored ({context}): {url} — {reason}"
                ),
                "url": url,
                "reason": reason,
                "context": context,
            }
        )
    return out


def _run_ingest(jobs: list[_AssetJob], *, core, store_root: str, snapshot) -> list[dict]:
    """Ingest every queued asset concurrently; return a diagnostic per REFUSED ingest.

    ``ingest_asset`` is called with ``raise_on_error=False`` so one bad asset cannot fail a
    whole ingestion — but the response used to be thrown away, which made a refused ingest
    indistinguishable from a successful one. The kit then carried an ``asset_id`` pointing at
    nothing. Now the refusal is returned and reported.
    """
    failures: list[dict] = []

    async def _drive() -> None:
        semaphore = asyncio.Semaphore(INGEST_CONCURRENCY)
        lock = asyncio.Lock()

        async def _one(job: _AssetJob) -> None:
            async with semaphore:
                failure = await asyncio.to_thread(
                    _ingest_one, job, core, store_root, snapshot
                )
            if failure is not None:
                async with lock:
                    failures.append(failure)

        await asyncio.gather(*(_one(job) for job in jobs))

    asyncio.run(_drive())
    return failures


def _ingest_one(job: _AssetJob, core, store_root: str, snapshot) -> dict | None:
    asset_id = f"asset_ing_{job.sha256[:16]}"
    # Content-addressed id → idempotent: the store dedupes bytes by digest, so
    # re-ingesting the same content is a no-op that returns the same record.
    try:
        response = _call_ingest(job, core, store_root, snapshot, asset_id)
    except Exception as error:  # noqa: BLE001 — one asset is not the ingestion
        # `raise_on_error=False` suppresses a REFUSAL, not a helper that died or a store
        # that is unreachable. Those used to propagate out of the gather and take the whole
        # ingestion with them; with every captured asset now rehosted, one bad byte string
        # could cost a human their entire brand kit. It costs a diagnostic instead.
        return {
            "code": "LUMI0515",
            "severity": "warning",
            "message": (
                f"asset ingest failed for {job.filename} "
                f"({job.url or 'no source url'}): {type(error).__name__}: {error}"
            ),
            "url": job.url,
            "reason": f"{type(error).__name__}: {error}",
            "context": "asset store ingest",
        }
    if isinstance(response, dict) and not response.get("ok", True):
        error_obj = response.get("error") or {}
        reason = (
            error_obj.get("message")
            or error_obj.get("code")
            or "the asset store refused it without saying why"
        )
        return {
            "code": "LUMI0515",
            "severity": "warning",
            "message": (
                f"asset ingest refused for {job.filename} "
                f"({job.url or 'no source url'}): {reason}"
            ),
            "url": job.url,
            "reason": str(reason),
            "context": "asset store ingest",
        }
    return None


def _call_ingest(job: _AssetJob, core, store_root: str, snapshot, asset_id: str):
    return core.ingest_asset(
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
