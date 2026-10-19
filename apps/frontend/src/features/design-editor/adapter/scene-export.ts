import {
  IMAGE_EXPORT_FORMATS,
  IMAGE_EXPORT_SCALES,
  imageExportSupportsScale,
  type ImageExportFormat,
  type ImageExportPreviewRenderMode,
  type ImageExportScale,
} from "@/features/chat-shell/model/image-export";
import type { ExportProfile, Scene } from "../engine/scene/contracts";
import type { EditorExportResult } from "../engine/scene/exportRunner";

/**
 * AD4.D step 1: the pure export adapter for the SCENE (ad) lane — the menu's
 * export vocabulary (docs/specs/ad-editor-integration/
 * ad-inspector-mapping-contract.md §1.11: formats PNG / SVG / PDF, scale 1x–4x
 * raster-only) translated into the engine's `ExportProfile` wire contract.
 *
 * Pure by construction: no React, no transport, no ambient environment. A
 * later slice hands these profiles to the `clue:artifact-export-request`
 * listener; this module only computes them.
 */

/** Screen-resolution raster. The engine's own `preview_png` profile pins the
 * same 96 dpi; the ad menu's 1x–4x scale multiplies it, so 4x is the
 * high-resolution deliverable rather than a separate print dpi. */
const PNG_EXPORT_DPI = 96;

/**
 * The ad menu's three export profiles (§1.11).
 *
 * `scale` applies to PNG alone — raster is a PNG-only parameter in the
 * ratified export model, mirrored by `imageExportSupportsScale` — so the SVG
 * and PDF profiles ignore the argument and carry `raster: null`.
 *
 * `embed_fonts` differs by format for one reason, stated by the engine's own
 * `defaultEditorExportProfile` (engine/scene/exportRunner.ts): a vector
 * deliverable "depends on viewer-installed fonts" without its own @font-face
 * payloads — and that applies twice over here, to the downloaded file AND to
 * the menu's collapsible preview region, which renders the result as an image
 * and so cannot reach document fonts. SVG and PDF must therefore carry their
 * glyph payloads; a PNG raster has already baked the glyphs into pixels, so
 * embedding fonts in it would be dead weight.
 *
 * `include_marks: false` is stated explicitly on every profile: the field is
 * optional on the wire, but per the contract's own comment the editor "sends
 * it on every profile it constructs".
 */
export function sceneExportProfile(
  format: ImageExportFormat,
  scale: 1 | 2 | 3 | 4
): ExportProfile {
  switch (format) {
    case "PNG":
      return {
        name: "ad_png",
        format: "png",
        pdf_intent: null,
        raster: { scale, dpi: PNG_EXPORT_DPI },
        include_bleed: false,
        include_marks: false,
        embed_fonts: false,
      };
    case "SVG":
      return {
        name: "ad_svg",
        format: "svg",
        pdf_intent: null,
        raster: null,
        include_bleed: false,
        include_marks: false,
        embed_fonts: true,
      };
    case "PDF":
      return {
        name: "ad_pdf",
        format: "pdf",
        // Digital intent. Print intent (with bleed and marks) enters only
        // after its mockups are approved — contract §1.11.
        pdf_intent: "preview",
        raster: null,
        include_bleed: false,
        include_marks: false,
        embed_fonts: true,
      };
  }
}

/** Characters no filesystem or Content-Disposition header should have to
 * carry: the Windows-reserved set plus ASCII control codes. A whole run
 * becomes ONE space so `Spring<<<>>>Sale` reads as two words, not eight. */
const FILENAME_HOSTILE_RUN = /[/\\:*?"<>|\u0000-\u001F]+/g;
const WHITESPACE_RUN = /\s+/g;

/** A title that sanitizes away to nothing still has to download as something. */
const FILENAME_FALLBACK = "export";

/**
 * The download filename for an ad export: a sanitized title plus the format's
 * extension (§1.11). Spaces are preserved — this is a human-facing filename,
 * not a URL slug, so it deliberately does NOT go through
 * `slugifyArtifactTitle` (the public-share slug) or the engine's
 * `safeFilenamePart` (which underscores every non-alphanumeric).
 */
export function exportFilename(title: string, format: ImageExportFormat): string {
  const sanitized =
    title
      .trim()
      .replace(FILENAME_HOSTILE_RUN, " ")
      .replace(WHITESPACE_RUN, " ")
      .trim() || FILENAME_FALLBACK;

  return `${sanitized}.${format.toLowerCase()}`;
}

/**
 * AD4.D step 2: what a `clue:artifact-export-request` event says, once it has
 * been established that it is a SCENE export at all.
 */
export interface SceneExportRequest {
  format: ImageExportFormat;
  /** The raster multiplier `sceneExportProfile` takes — 1 unless the detail
   * carried one of the menu's own `1x`–`4x` labels. */
  scale: 1 | 2 | 3 | 4;
  /** The requester's own title for the download, or null when it sent none
   * (the sharing menu's shape) — the listener supplies its fallback. */
  title: string | null;
}

/**
 * The menu's scale label as the raster multiplier `sceneExportProfile` takes.
 *
 * One function, two callers, deliberately: the download listener reaches it
 * through `parseSceneExportRequest` (an untrusted event detail) and the preview
 * leg calls it directly with the menu's own typed value. If the two ever mapped
 * differently, a preview would be cached under a key whose download rasterizes
 * at another size — the same picture at two resolutions, silently.
 *
 * Anything absent or unrecognized is 1x rather than a refusal: scale is a
 * PNG-only parameter (`imageExportSupportsScale`), so the two formats that carry
 * none are the menu's ordinary shape, and `sceneExportProfile` ignores the
 * argument for them anyway.
 */
export function sceneExportScaleMultiplier(scale: unknown): 1 | 2 | 3 | 4 {
  // ARITHMETIC, not a parallel lookup array (final review, finding 2). The
  // menu's scale vocabulary is `Nx` for a single digit, so the index into
  // `IMAGE_EXPORT_SCALES` IS the multiplier minus one — a second array holding
  // `[1,2,3,4]` only created a way for the two to fall out of step, and with
  // `noUncheckedIndexedAccess` off its indexing was unchecked besides.
  const index = IMAGE_EXPORT_SCALES.indexOf(scale as ImageExportScale);
  return index === -1 ? 1 : ((index + 1) as 1 | 2 | 3 | 4);
}

/**
 * What the export menu says about the last attempt, and whether that attempt
 * produced a file.
 *
 * `failed` is deliberately TWO-VALUED — "the user asked for a file and there is
 * no file" — not a severity scale. It exists so the menu can make a refusal
 * VISIBLE (`image-export-menu.tsx`); before it, every outcome went only to a
 * `.srOnly` span, so a preflight-blocked export looked to a sighted user like a
 * button that does nothing, and the founder clicked it repeatedly. The advisory
 * / blocking severity split of the export response itself is spec P0.3 + ruling
 * R5 and is owned elsewhere; nothing here anticipates it.
 */
export interface SceneExportStatus {
  failed: boolean;
  message: string;
}

/**
 * Which stamped status the export menu shows.
 *
 * A status is STAMPED with the document it is about and only shown under
 * that document, so switching artifacts cannot inherit the previous ad's
 * outcome. The `null` stamp is the deliberate exception (final review, finding
 * 3): a refusal issued while NO document was loaded is not about a document at
 * all, so it must not evaporate the moment one arrives. It used to — and
 * because the menu reads `exportStatus ?? controller.statusMessage`, the span
 * then fell back to the controller's optimistic "PNG export requested at 1x"
 * about an export that had just been refused and never ran. Announcing a
 * fiction is precisely the defect R-D7 exists to prevent, so the refusal
 * outlives the arrival and stands until a real attempt replaces it.
 */
export function exportStatusFor(
  status: (SceneExportStatus & { forDocumentId: string | null }) | null,
  documentId: string | null,
): SceneExportStatus | null {
  if (!status) {
    return null;
  }
  if (status.forDocumentId === null || status.forDocumentId === documentId) {
    return { failed: status.failed, message: status.message };
  }
  return null;
}

/**
 * The listener's gate, as a pure decision: `null` means "not this lane's
 * export", and the listener returns silently — the same `clue:artifact-export-request`
 * name is dispatched by the image-export menu
 * (`use-image-export-controller.ts:39`, `{format, kind, scale?, title}`) AND by
 * the sharing menu (`use-artifact-sharing-controller.ts:181`, `{format: "ZIP" |
 * "PDF", kind}`), so both shapes reach every listener on the window.
 *
 * The FORMAT guard is load-bearing, not defensive padding (D1 review
 * carry-forward): `sceneExportProfile` is a total switch over the three menu
 * formats, so an unvalidated `"ZIP"` — which the sharing menu really does send
 * with `kind: "ad"` — returns `undefined` at runtime and would be posted to the
 * export endpoint as a profile-shaped hole. Nothing downstream re-checks it.
 *
 * The scale is read by the shared `sceneExportScaleMultiplier`, which is where
 * the "absent or unrecognized is 1x, not a refusal" reasoning lives — the same
 * mapping the preview leg uses, so the two can never disagree.
 */
export function parseSceneExportRequest(detail: unknown): SceneExportRequest | null {
  if (typeof detail !== "object" || detail === null) {
    return null;
  }
  const { format, kind, scale, title } = detail as {
    format?: unknown;
    kind?: unknown;
    scale?: unknown;
    title?: unknown;
  };
  // The kind guard is what keeps the two lanes' listeners apart on one window,
  // exactly as it does for the action-menu requests
  // (`use-scene-inspector-writes.ts`).
  if (kind !== "ad") {
    return null;
  }
  if (!IMAGE_EXPORT_FORMATS.includes(format as ImageExportFormat)) {
    return null;
  }
  return {
    format: format as ImageExportFormat,
    scale: sceneExportScaleMultiplier(scale),
    title: typeof title === "string" && title.length > 0 ? title : null,
  };
}

/**
 * The one line the menu's `aria-live` span reads when an export finishes.
 *
 * A failure speaks in the ENGINE's words — the first blocking error's `message` —
 * because a generic "export failed" hides the one fact the user can act on (a
 * raster budget exceeded at 4x, a missing font). The generic line is the
 * fallback for a failure that arrived carrying nothing sayable: a blank message
 * would announce an empty status, which reads as no failure at all.
 */
export function sceneExportResultMessage(
  format: ImageExportFormat,
  result: EditorExportResult,
): string {
  if (result.status === "ok") {
    return `${format} exported`;
  }
  // Name what actually blocked: the first error the API did not let through. A warning (a font
  // licence flag that only matters for PDF) never blocks an export, so it is never the reason.
  const advisory = new Set(result.advisoryCodes);
  const blocking = result.diagnostics.find(
    (item) => item.severity === "error" && !advisory.has(item.code) && item.message.trim() !== "",
  );
  return blocking ? blocking.message : `${format} export failed`;
}

/**
 * AD4.D step 3 (§1.11): the export preview's `(format, scale)` cache, as a
 * plain value with pure decisions over it.
 *
 * ── WHAT MAKES A CACHED RENDER STILL TRUE (ruling R-D13) ────────────────────
 * The plan says "cache until the document version changes". The cache's anchor
 * is the session's LIVE SCENE OBJECT IDENTITY, which is the strict proxy for
 * that: the engine mirrors a NEW scene object up on every accepted write, every
 * reload and every agent turn, so `cachedScene !== currentScene` is true
 * whenever the version moved. It is deliberately stricter than a version
 * comparison — a same-version reload also invalidates, costing one extra export
 * and never showing a stale picture. The scene is an IDENTITY ANCHOR and is
 * never inspected; nothing here reads a field off it.
 *
 * That strictness is the whole point. This is the AD4.R MVP state model's rule
 * for React-held state: the accepted engine scene owns document truth, and a
 * cached preview is operation feedback keyed on that truth. An image of a scene
 * the document no longer holds must never be served.
 *
 * No eviction cap: the key space is 3 formats x 4 scales, and every entry dies
 * with its scene anyway.
 */
export interface SceneExportPreviewCache {
  /** The document the entries were rendered for. */
  forDocumentId: string;
  /** The scene object the entries were rendered from — an identity anchor, read
   * with `!==` and nothing else. */
  forScene: Scene;
  /** `previewCacheKey(...)` → the render's `data_url`. */
  entries: ReadonlyMap<string, string>;
}

/**
 * PORTED, not imported, from the standalone editor's
 * `subsystems/clue-design/apps/editor/src/components/ExportPreviewSurface.tsx`
 * (`ArtifactPreview`, lines 64–77): it branches `artifact.format === "pdf"` to
 * an `<iframe src={data_url}>` and sends every other format to an `<img>`.
 * Nothing here may import from `subsystems/`, so the branch is mirrored. Same
 * reason upstream has it: `<img src="data:application/pdf,…">` is a
 * broken-image glyph in every browser, and a browser's own PDF viewer is what
 * renders a PDF in a frame.
 *
 * ONE deviation from upstream, deliberate: upstream branches on the ARTIFACT's
 * declared `format`, this branches on the payload's OWN declared media type.
 * The engine, not this file, decides what actually comes back for a
 * `pdf_intent: "preview"` profile, and reading the payload stays correct
 * whichever it is. It also gives the honest third arm upstream has no need for:
 * a payload that is neither an image nor a PDF renders NOTHING — treated
 * exactly like a pending or a failed one, the designed empty region with no
 * announcement (ruling R-D14) — rather than a broken element. The export still
 * ran and is still cached either way, and the download leg delivers those same
 * bytes as a file perfectly well.
 */
export function previewRenderMode(dataUrl: string): ImageExportPreviewRenderMode | null {
  if (/^data:image\//i.test(dataUrl)) {
    return "img";
  }
  if (/^data:application\/pdf[;,]/i.test(dataUrl)) {
    return "iframe";
  }
  return null;
}

/**
 * Whether something anchored to a `(document, scene)` pair is still anchored to
 * the LIVE one — the R-D13 identity comparison, in one place.
 *
 * Written once because three separate mechanisms depend on agreeing about it
 * exactly: the cache lookup, the cache store, and the preview leg's in-flight
 * registry. If any one of them compared anchors differently the others' safety
 * would be silently void — an in-flight guard that disagrees with the cache is
 * how a request for a moved-on scene gets swallowed by an export that is
 * already destined for the discard path.
 */
export function previewAnchorsMatch<
  Anchored extends { forDocumentId: string; forScene: Scene },
>(
  anchored: Anchored | null,
  documentId: string,
  scene: Scene,
): anchored is Anchored {
  return (
    anchored !== null &&
    anchored.forDocumentId === documentId &&
    anchored.forScene === scene
  );
}

/**
 * The cache key for one preview render.
 *
 * SVG and PDF key at scale 1 whatever the menu's scale says, because their
 * profiles do not vary by scale (`sceneExportProfile` ignores the argument for
 * them, as D1 pinned) — so flipping 2x→4x while the format is SVG must be a
 * cache HIT, not a second identical export. The menu keeps its scale selection
 * across a format flip, so this case is ordinary, not exotic.
 */
export function previewCacheKey(format: ImageExportFormat, scale: 1 | 2 | 3 | 4): string {
  return `${format}:${imageExportSupportsScale(format) ? scale : 1}`;
}

/** The cached render for `key`, or `null` when there is none that is still true
 * of this document and this scene. */
export function previewCacheLookup(
  cache: SceneExportPreviewCache | null,
  documentId: string,
  scene: Scene,
  key: string,
): string | null {
  if (!previewAnchorsMatch(cache, documentId, scene)) {
    return null;
  }
  return cache.entries.get(key) ?? null;
}

/**
 * The cache with `key` → `dataUrl` added.
 *
 * When either anchor has moved the whole cache is REPLACED — a fresh entries map
 * under the new anchors — rather than extended. Keeping the old entries around
 * "in case the user goes back" would mean holding renders of a superseded scene,
 * which is precisely the thing that must never be served; and a superseded scene
 * object is not coming back (the engine mirrors up a new one each time).
 */
export function previewCacheStore(
  cache: SceneExportPreviewCache | null,
  documentId: string,
  scene: Scene,
  key: string,
  dataUrl: string,
): SceneExportPreviewCache {
  const carried = previewAnchorsMatch(cache, documentId, scene) ? cache.entries : null;
  const entries = new Map(carried ?? []);
  entries.set(key, dataUrl);
  return { forDocumentId: documentId, forScene: scene, entries };
}
