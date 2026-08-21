import type { AssetId, AssetRecord, Node, Scene } from "../engine/scene/contracts";
import {
  assetRecordPassthroughUrl,
  sceneAssetPassthroughUrl,
} from "./scene-canvas-view";
import { sceneImageReplacementTarget } from "./scene-apply";

/**
 * AD4.A step 3 (§1.3 row 2): the PURE half of the image AI suite — the request
 * shaping and the gates behind Generate / Edit / Remove background / candidate
 * review, with no React and no transport.
 *
 * WHY IT IS A FILE OF ITS OWN. `scene-apply.ts` answers one question — "which
 * operation does this change produce?" — and the AI suite's *document* answer
 * is already there beside its §1.3 siblings
 * (`sceneImagePlacementOperations`).
 * What is here is everything that happens BEFORE a document change exists: what
 * to ask the model for, and whether to ask at all. That is a different question
 * with a different shape (it reads the scene's asset registry, not a node's
 * fields), and it is the same split `scene-palette.ts` and `scene-history.ts`
 * already make on this lane.
 *
 * EVERY RULE HERE IS UPSTREAM'S, ported rather than invented —
 * `subsystems/clue-design/apps/editor/src/components/ImageInspectorSection.tsx`
 * is the source, and each function names the upstream member it lifts. The
 * divergences are stated at their sites and are all of one kind: this lane
 * refuses where upstream substitutes, because §4's lock and the platform's
 * "never mint an asset you cannot place" rule bind here and do not there.
 *
 * WHAT IS DELIBERATELY ABSENT: the focal-point fields. Upstream's AI section
 * carries Focal X / Focal Y number inputs beside these controls; they are the
 * same §6-gated crop control as the canvas dot (Gate G-C, OPEN), so they are
 * not ported. Alt text is a separate row and IS in scope — it rides the
 * ordinary property seam (`scene-apply.ts`'s `altText` case), not this file.
 */

/** Upstream's `IMAGE_LONG_EDGE` — the long edge every generation request asks
 * for, with the node's own aspect preserved around it. */
export const IMAGE_LONG_EDGE = 1536;

/** Upstream's `REMOVE_BACKGROUND_INSTRUCTION`, verbatim: the one-click
 * affordance is the SAME `/assets/generate` edit call with a fixed prompt, not
 * a route of its own. (It is unrelated to Gate G-E, which holds the export
 * raster's transparency checkbox — a different mechanism on a different
 * endpoint.) */
export const REMOVE_BACKGROUND_INSTRUCTION = "Remove the background completely";

/** Upstream's `label: trimmed.slice(0, 60)`. The API applies the same cut when
 * a request carries no label at all (`main.py`'s `payload.label or
 * payload.prompt[:60]`), so this is parity on both sides of the seam. */
export const GENERATED_LABEL_LENGTH = 60;

export interface SceneImageResolution {
  height: number;
  width: number;
}

/** What the panel needs to SHOW a staged candidate — a label and a URL, never
 * an `AssetRecord`. Presentation may not import the engine, so the record stops
 * at this seam exactly as `SceneInspectorState` stops the scene at its own. */
export interface SceneImageCandidateView {
  label: string;
  previewSrc: string | null;
}

/**
 * §1.3 row 2: everything the ad inspector's AI rows are DRIVEN by — the one
 * prop the panel takes for the whole suite.
 *
 * It is declared beside the decisions rather than in the component for
 * `SceneInspectorState`'s reason exactly: presentation may not import the
 * engine, so the `AssetRecord`, the `Scene` and the transport all stop at this
 * seam, and the panel is handed strings, booleans and callbacks. Absent (the
 * dummy fixture path) the AI rows do not render at all, which is what the
 * schema shipped as.
 */
export interface SceneImageAiBinding {
  /** The BEFORE half of the review — the node's own asset, through the same
   * public passthrough the artboard paints from, or null when it has none.
   * Never the dummy's stock png: a stranger's photograph captioned "Before"
   * would not be a wrong thumbnail, it would be a wrong ANSWER. */
  beforeSrc: string | null;
  /** The staged edit awaiting review, or null when there is nothing to answer. */
  candidate: SceneImageCandidateView | null;
  /** Whether the Edit / Remove-background block may render — a ready, unlocked
   * source asset exists (`sceneImageEditSource`). */
  canEdit: boolean;
  editing: boolean;
  generating: boolean;
  /** Whether the node already carries a picture — the one thing that changes
   * the Generate button's own word (upstream's `hasImage`). */
  hasImage: boolean;
  onAccept: () => void;
  onEdit: (instruction: string) => void;
  onGenerate: (prompt: string) => void;
  onRejectCandidate: () => void;
  onRemoveBackground: () => void;
  onSaveCandidateAsNew: () => void;
  /** What a Save-as-new confirmed, until the next attempt supersedes it. */
  savedNotice: string | null;
  /** The asset status line, or null — which is most of the time
   * (`sceneImageStatusLine` states why). */
  statusLine: string | null;
}

/**
 * §1.3 Generate: the resolution one generation asks for — upstream's
 * `frameResolution`, ported literally.
 *
 * The solved `computed.layout_bounds` wins because that is the box the picture
 * will actually occupy; the declared FIXED size is the fallback. `computed` is
 * null on every stored node (the harvest's own header records this), so at rest
 * the fallback is the live path and the computed branch only fires on the
 * relaid scene the canvas mirrors up.
 *
 * A hug or fill axis therefore has no number at all, and this states
 * `undefined` rather than guessing one — the request then simply carries no
 * width/height, which is upstream's own behaviour and the API's documented
 * default. Same for a collapsed (zero or negative) box: a 0-pixel request is
 * not a smaller picture, it is a refusal with extra steps.
 */
export function sceneGenerationResolution(
  node: Node,
): SceneImageResolution | undefined {
  const bounds = node.computed?.layout_bounds;
  let width = bounds?.width;
  let height = bounds?.height;
  if (!width || !height) {
    if (node.size.width.kind === "fixed") {
      width = node.size.width.value;
    }
    if (node.size.height.kind === "fixed") {
      height = node.size.height.value;
    }
  }
  if (!width || !height || width <= 0 || height <= 0) {
    return undefined;
  }
  return width >= height
    ? {
        height: Math.max(1, Math.round((IMAGE_LONG_EDGE * height) / width)),
        width: IMAGE_LONG_EDGE,
      }
    : {
        height: IMAGE_LONG_EDGE,
        width: Math.max(1, Math.round((IMAGE_LONG_EDGE * width) / height)),
      };
}

/** §1.3 Generate/Edit: the label a minted asset carries — the trimmed prompt,
 * cut at 60 characters (upstream's `trimmed.slice(0, 60)`). It is also what a
 * placement falls back to when the node has no alt text of its own
 * (`withDefaultAlt`), which is why the cut happens here rather than being left
 * to the API. */
export function sceneGeneratedAssetLabel(prompt: string): string {
  return prompt.trim().slice(0, GENERATED_LABEL_LENGTH);
}

/**
 * §1.3 Edit / §4: the asset an edit would run against, or `null` when the
 * Edit / Remove-background block must not be offered at all.
 *
 * Upstream's `canEdit` is `hasImage && sourceAssetId && (asset?.status ??
 * "ready") === "ready"`, and all three clauses are here. Two notes:
 *
 *  • THE LOCK IS OURS, not upstream's. Upstream gates the whole section on a
 *    `disabled` prop; on this lane §4's lock is asked through the SAME
 *    predicate every other §1.3 row asks (`sceneImageReplacementTarget`), so
 *    the three image-minting flows cannot drift apart. It matters here for the
 *    reason it matters at the upload: an edit that mints a real asset the
 *    editor can never place is a half write — a registry row nothing
 *    references — so the refusal must happen BEFORE the spend.
 *  • AN UNKNOWN ASSET IS TREATED AS READY, which is upstream's `?? "ready"`
 *    verbatim. The scene's asset map is not the registry: a record it does not
 *    carry is missing evidence, not evidence of a broken asset.
 */
export function sceneImageEditSource(node: Node, scene: Scene): AssetId | null {
  const image = sceneImageReplacementTarget(node);
  if (!image?.asset_id) {
    return null;
  }
  const status = scene.assets?.[image.asset_id]?.status ?? "ready";
  return status === "ready" ? image.asset_id : null;
}

/** §1.3 Review: what the panel shows for a staged candidate. The URL is the
 * public, content-addressed passthrough the artboard and the Fill thumbnail
 * already paint from — one route for every picture in this panel. */
export function sceneImageCandidateView(
  record: AssetRecord,
): SceneImageCandidateView {
  return {
    label: record.label,
    previewSrc: assetRecordPassthroughUrl(record),
  };
}

/** §1.3 Review: the BEFORE half — the picture the node carries right now,
 * resolved exactly as the artboard and the Fill thumbnail resolve it, so the
 * three can never disagree about which bytes this node holds. Null for a
 * non-image node, and for an asset with no usable digest. */
export function sceneImageBeforeSrc(node: Node, scene: Scene): string | null {
  if (node.kind.kind !== "image") {
    return null;
  }
  return sceneAssetPassthroughUrl(scene.assets, node.kind.asset_id);
}

/**
 * §1.3 row 2: the asset status line — or `null`, which is most of the time.
 *
 * Upstream derives one line from four facts and renders it always. Three of
 * them are already stated better here and are deliberately NOT repeated:
 * "generating" is the Generate button's own label, a failure is the panel's
 * existing inline error slot (the one every write on this lane uses), and a
 * READY asset is the Fill thumbnail directly above, which shows the picture
 * itself. Repeating them would be three lines of chrome restating what is on
 * screen.
 *
 * What is left is the two states nothing else on the panel says, and they are
 * exactly the two that explain a MISSING Edit block:
 *   • the node carries no asset at all;
 *   • its asset is not `ready` (pending / failed / archived), so there are no
 *     pixels to edit.
 * Both use upstream's own words. The empty case drops upstream's trailing
 * clause ("— generate or place one from the asset library"), and the trim is
 * AMENDMENT 4's own precedent rather than licence to edit copy: G-D shipped the
 * MVP's banners verbatim except the command chip, which was re-pointed at this
 * repo's remedy because "instructions that cannot be followed are not copy". A
 * clause naming an asset-library surface the platform does not expose is the
 * same case. The rest is verbatim.
 */
export function sceneImageStatusLine(node: Node, scene: Scene): string | null {
  if (node.kind.kind !== "image") {
    return null;
  }
  const assetId = node.kind.asset_id;
  if (!assetId) {
    return "No image yet";
  }
  // An asset the scene does not carry is missing evidence, not a broken asset —
  // the same `?? "ready"` default the edit gate above applies.
  const status = scene.assets?.[assetId]?.status ?? "ready";
  return status === "ready" ? null : `Asset ${assetId} · ${status}`;
}
