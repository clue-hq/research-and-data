"use client";

import { useCallback, useEffect, useRef } from "react";
import { mintNodeId } from "../adapter/scene-clipboard";
import { isAllowedImage } from "../adapter/scene-clipboard-classify";
import {
  PASTE_CASCADE_STEP,
  planPastePlacement,
  type PastePlacement,
  type PastePlacementMode,
} from "../adapter/scene-clipboard-placement";
import { uploadWebAsset } from "../data/assets";
import type {
  AssetRecord,
  Node,
  NodeId,
  Operation,
  PageId,
  ParentRef,
  Scene,
  Transform,
} from "../engine/scene/contracts";
import { insertNode } from "../engine/scene/operations";
import { NOT_ACCEPTING_EDITS, parentOriginOf } from "./use-scene-clipboard";

/**
 * Scene clipboard Task 8 — external image ingestion: a picture that came from
 * OUTSIDE this document (a ⌘V of files, a drag-drop onto the stage, or pasted
 * svg markup) becomes an uploaded asset and one image node.
 *
 * Task 7 left three seams on `useSceneClipboard`; this file fills two of them
 * (`onExternalImages`, `onSvgMarkup`) and adds the third gesture the clipboard
 * cannot see at all — the canvas drop. `onPlainText` is Task 9's and is not
 * touched here.
 *
 * ── ONE PATH, THREE GESTURES ──────────────────────────────────────────────
 * Everything converges on {@link ingestExternalImages}. Pasted svg markup is
 * turned into a `File` first ({@link svgMarkupToFile}) rather than given its
 * own branch: the asset store already ingests svg, so a second code path would
 * be a second set of refusals to keep in step. The three gestures differ in
 * exactly one thing — WHERE the picture lands (the dropped page point, or the
 * viewport's centre) — which is the placement mode they pass in.
 *
 * ── WHAT IS AND IS NOT DECIDED HERE ───────────────────────────────────────
 * The placement is the Task-4 planner's (`planPastePlacement`), the node ids
 * are the Task-3 minter's (`mintNodeId`), the allowlist is the Task-6
 * classifier's (`isAllowedImage`), the operations are the engine's
 * (`insertNode`), and the upload is the platform's one asset client
 * (`uploadWebAsset`). What this file owns is the SEQUENCING — gate, refuse
 * early, spend, re-gate, size, place, apply — and the two sizing/refusal rules
 * ratified for it (R22–R25).
 *
 * ── ATOMICITY (R20) ───────────────────────────────────────────────────────
 * A gesture is one undo frame: every file uploads through `Promise.allSettled`
 * (one failure never cancels its siblings), the survivors are applied in ONE
 * `applyOps`, and every refusal is joined into ONE `reportError`. A gesture
 * with no survivors applies nothing and still reports — a picture that did not
 * land must never be silent.
 *
 * ── THE GATE IS ASKED TWICE, BECAUSE THIS PATH SPENDS ─────────────────────
 * `canApply` is asked before the upload and again before the write, the
 * AD4.A replace-image precedent: an upload mints a real asset-registry row, so
 * a refusal discovered after it would strand one. Both refusals speak Task 7's
 * sentence, so the user meets one vocabulary for one state.
 */

/** R23: the client-side byte cap, mirroring the server default
 * `py_lumen_config/config.py::lumen_asset_max_bytes` (10 MiB). It is a courtesy
 * gate, not the authority — a file that slips past it still meets the server's
 * own 413, whose detail is surfaced verbatim. */
export const CLIENT_ASSET_MAX_BYTES = 10 * 1024 * 1024;

/** The undo-frame label for one ingestion gesture (R20). */
export const IMAGE_PASTE_INTENT = "clipboard.image-paste";

/** R25: a pasted picture fits inside 60% of the page's SHORT side. */
const SHORT_SIDE_FRACTION = 0.6;

/** The name a pasted svg document is ingested under. Markup arrives with no
 * filename at all, and the label is what the user is shown when the record
 * refuses — so it has to be something, and something honest. */
const PASTED_SVG_FILENAME = "pasted.svg";

/** The one sentence for "this gesture cannot be placed on a page", which is
 * reachable on a pageless document (`open_design_leg@4` births one). */
const NO_PAGE_TO_PLACE_ON = "This design has no page to place an image on.";

/**
 * R25 (ratified): the size a pasted image is born at — its intrinsic aspect,
 * fitted inside a box 60% of the page's SHORT side, DOWNSCALE-ONLY.
 *
 * Downscale-only is the whole rule's point: a 4000x2000 screenshot on a
 * 1080x1080 page arrives at 648x324 instead of eight times off the canvas,
 * while a 200x100 icon arrives at 200x100 rather than blown up into a blurry
 * 648-wide smear.
 *
 * Pure by construction — it takes a plain intrinsic pair and a plain page pair,
 * never an `AssetRecord` or a `Scene`, so the rule is testable without either.
 */
export function pastedImageNodeSize(
  media: { width: number; height: number },
  page: { width: number; height: number },
): { width: number; height: number } {
  const limit = SHORT_SIDE_FRACTION * Math.min(page.width, page.height);
  // A page that measures nothing (or nonsense) licenses no box at all: the
  // picture keeps its own size rather than being scaled by a NaN.
  if (!isPositiveFinite(limit) || !isPositiveFinite(media.width) || !isPositiveFinite(media.height)) {
    return { width: media.width, height: media.height };
  }
  const scale = Math.min(1, limit / media.width, limit / media.height);
  return {
    width: roundForScene(media.width * scale),
    height: roundForScene(media.height * scale),
  };
}

/**
 * Pasted svg markup as an `image/svg+xml` file, so it rides the one ingestion
 * path every other picture rides.
 */
export function svgMarkupToFile(svg: string): File {
  return new File([svg], PASTED_SVG_FILENAME, { type: "image/svg+xml" });
}

/** WHERE a gesture's pictures land, captured at gesture time.
 *
 * The MODE's anchor (the dropped page point, or the viewport centre) is
 * captured when the user acts; the scene it is planned against is read again
 * after the uploads settle, because an agent turn or another edit may have
 * moved the document while the bytes travelled. The selection is likewise the
 * one the user had when they acted.
 */
export interface ExternalImagePlacement {
  mode: PastePlacementMode;
  pageId: PageId;
  selectedNodeId: NodeId | null;
}

export interface ExternalImageIngestDeps {
  /** The manual-edits controller's write path. One call per gesture (R20). */
  applyOps: (operations: Operation[], intent?: string) => boolean;
  /** Asked BEFORE the upload and again before the write — an upload spends. */
  canApply: () => boolean;
  /** R10's PARENT-keyed origin adapter, applied to the scene read after the
   * uploads settle. Injected rather than reached for so the rebase is
   * testable, and shared with Task 7 rather than copied. */
  parentOrigin: (scene: Scene) => (parentId: NodeId) => { x: number; y: number };
  reportError: (message: string) => void;
  /** The CURRENT scene, re-read after the uploads settle. */
  scene: () => Scene | null;
  upload: (file: File) => Promise<AssetRecord>;
}

export interface ExternalImageIngestOutcome {
  inserted: number;
  refusals: string[];
}

/**
 * Ingest one gesture's worth of files: upload them all, place the ones that
 * came back usable, and say — once — what did not land.
 *
 * `alreadyRejected` carries the names the Task-6 classifier dropped before this
 * was called (a ⌘V of a PNG *and* a GIF hands over one file and one name). They
 * are refused in the same words a disallowed drop is, because from the user's
 * side those are the same event: pictures went in, one did not arrive.
 */
export async function ingestExternalImages(
  files: File[],
  placement: ExternalImagePlacement,
  deps: ExternalImageIngestDeps,
  alreadyRejected: readonly string[] = [],
): Promise<ExternalImageIngestOutcome> {
  if (files.length === 0 && alreadyRejected.length === 0) {
    return { inserted: 0, refusals: [] };
  }
  // Accumulated from here on, and never discarded: a whole-gesture bail below
  // states its own reason FIRST and then everything already refused per file
  // (R20 — "each naming the file and reason"). Dropping them would leave a
  // dropped GIF unexplained just because the document also went read-only.
  const refusals: string[] = alreadyRejected.map(unsupportedTypeRefusal);

  // PRECEDENCE, Task 7's verbatim: the read-only sentence outranks the
  // allowlist one — it is the state that actually refused, so it leads.
  if (!deps.canApply()) {
    return refuse(deps, [NOT_ACCEPTING_EDITS, ...refusals]);
  }

  const accepted: File[] = [];
  for (const file of files) {
    if (!isAllowedImage(file)) {
      refusals.push(unsupportedTypeRefusal(file.name));
    } else if (file.size > CLIENT_ASSET_MAX_BYTES) {
      // R23: refused BEFORE the transport — a 40 MB upload that the server was
      // always going to refuse is a minute of the user's bandwidth for nothing.
      refusals.push(oversizeRefusal(file.name));
    } else {
      accepted.push(file);
    }
  }
  if (accepted.length === 0) {
    return refuse(deps, refusals);
  }

  // R20: every file of the gesture is attempted. `allSettled`, never `all` —
  // one refused picture must not cancel the three that were fine.
  const settled = await Promise.allSettled(
    accepted.map((file) => deps.upload(file)),
  );

  // Planned against the scene as it is NOW, not as it was when the user acted.
  const scene = deps.scene();
  const page = scene?.pages[placement.pageId] ?? null;
  if (!scene || !page) {
    return refuse(deps, [NO_PAGE_TO_PLACE_ON, ...refusals]);
  }
  // The re-gate (AD4.A precedent): the lock can be turned on, or the engine can
  // go read-only, while the bytes travel.
  if (!deps.canApply()) {
    return refuse(deps, [NOT_ACCEPTING_EDITS, ...refusals]);
  }

  const pageSize = { width: page.size.width, height: page.size.height };
  const originOf = deps.parentOrigin(scene);
  const taken = new Set(Object.keys(scene.nodes));
  const operations: Operation[] = [];
  /** Pictures placed so far — the R24 fan-out ordinal and the seat step. It is
   * counted separately from `operations.length` because each picture emits TWO
   * operations (see the batch below). */
  let placed = 0;

  settled.forEach((result, fileIndex) => {
    const file = accepted[fileIndex];
    if (result.status === "rejected") {
      // The API's own diagnostic, verbatim — it is the only source that knows
      // why (a 413 cap, a license refusal, an unreadable body).
      refusals.push(`${file.name}: ${messageOf(result.reason)}`);
      return;
    }
    const record = result.value;
    if (record.status !== "ready") {
      refusals.push(notReadyRefusal(record));
      return;
    }
    const intrinsic = intrinsicSize(record);
    if (!intrinsic) {
      // R22: no honest size to draw at. A guessed box would be a picture the
      // user has to fix on every paste.
      refusals.push(`couldn't read image dimensions for ${file.name}`);
      return;
    }
    const size = pastedImageNodeSize(intrinsic, pageSize);
    const planned = planPastePlacement({
      mode: placement.mode,
      pageId: placement.pageId,
      parentComputedOrigin: originOf,
      // Only the SIZE of these bounds is read by the drop-point and
      // viewport-center anchors — the box has no prior position to cascade off.
      payloadBounds: { x: 0, y: 0, width: size.width, height: size.height },
      scene,
      selectedNodeId: placement.selectedNodeId,
    });
    // R24: the Nth picture of one gesture steps clear of the (N-1)th, so a
    // four-file drop is four visible pictures rather than one on top of three.
    const ordinal = placed;
    const nodeId = mintNodeId((candidate) => taken.has(candidate));
    taken.add(nodeId);
    // REGISTER, THEN INSERT — the canonical pair, and the order is
    // load-bearing rather than stylistic. A node whose `asset_id` names a
    // record the document does not hold resolves to no bytes at all
    // (`sceneAssetPassthroughUrl` reads `scene.assets[id]`, so the canvas draws
    // a blank box) and fails the engine's strict asset validation. It is the
    // same first half `buildNodePlacementOperations` emits
    // (`engine/scene/assetLibrary.ts:326-341`) — the shipped Replace-image /
    // Generate / Accept paths all lead with it. Both operations ride the ONE
    // `applyOps` below, so a picture is still exactly one undo frame.
    operations.push({ kind: "upsert_asset", asset: record });
    operations.push(
      insertNode(
        planned.parent,
        seatIndex(scene, planned) + ordinal,
        imageNode(nodeId, file.name, record.id, size, fannedTransform(planned, ordinal)),
      ),
    );
    placed += 1;
  });

  let inserted = 0;
  if (operations.length > 0 && deps.applyOps(operations, IMAGE_PASTE_INTENT)) {
    inserted = placed;
  }
  if (refusals.length > 0) {
    deps.reportError(refusals.join("; "));
  }
  return { inserted, refusals };
}

/** One message, nothing applied — the shape every whole-gesture refusal takes. */
function refuse(
  deps: ExternalImageIngestDeps,
  refusals: string[],
): ExternalImageIngestOutcome {
  if (refusals.length > 0) {
    deps.reportError(refusals.join("; "));
  }
  return { inserted: 0, refusals };
}

/** The seat the FIRST picture of a gesture takes under its planned parent: the
 * planner's index for an auto-layout insert, and the end of the child list for
 * a freehand one — the materializer's own convention
 * (`scene-clipboard.ts::materializeClipboardPayload`), so both paste paths
 * append the same way. */
function seatIndex(scene: Scene, placement: PastePlacement): number {
  if (placement.kind === "into-layout") {
    return placement.index;
  }
  return childIdsOf(scene, placement.parent).length;
}

function childIdsOf(scene: Scene, parent: ParentRef): readonly NodeId[] {
  const container =
    parent.kind === "page" ? scene.pages[parent.id] : scene.nodes[parent.id];
  return container?.children ?? [];
}

/** R24's offset, applied to the freehand transform only: an into-layout child's
 * position belongs to the solver, and an authored transform there would be
 * overwritten on the next solve (the Task-4 planner's own rule). */
function fannedTransform(placement: PastePlacement, ordinal: number): Transform {
  if (placement.kind === "into-layout") {
    return ZERO_TRANSFORM;
  }
  const step = PASTE_CASCADE_STEP * ordinal;
  return {
    ...placement.transform,
    x: placement.transform.x + step,
    y: placement.transform.y + step,
  };
}

const ZERO_TRANSFORM: Transform = {
  x: 0,
  y: 0,
  rotation: 0,
  skew_x: 0,
  skew_y: 0,
  flip_x: false,
  flip_y: false,
};

/** The node one ingested picture becomes. Childless and unstyled: an image node
 * is its asset, its box and nothing else, and `computed` is the engine's to
 * solve — never ours to author. */
function imageNode(
  id: NodeId,
  fileName: string,
  assetId: string,
  size: { width: number; height: number },
  transform: Transform,
): Node {
  return {
    id,
    name: fileName,
    // The file name is the honest alt text: it is what the user called the
    // picture, and an empty alt on a fresh node is a thing nobody goes back to
    // fill in.
    kind: { kind: "image", asset_id: assetId, alt: fileName },
    transform,
    size: {
      width: { kind: "fixed", value: size.width },
      height: { kind: "fixed", value: size.height },
    },
    children: [],
    fills: [],
    strokes: [],
    corner: { top_left: 0, top_right: 0, bottom_right: 0, bottom_left: 0 },
    opacity: 1,
    clip: false,
    layout: null,
    computed: null,
    locked: false,
  };
}

/**
 * R22: the intrinsic pixel box, from whichever metadata block this record
 * actually carries — `raster` for a PNG/JPEG/WebP, `vector` for an SVG, whose
 * width and height are both NULLABLE. Null when neither answers, which is a
 * refusal upstream rather than a guessed box.
 */
function intrinsicSize(
  record: AssetRecord,
): { width: number; height: number } | null {
  const raster = record.raster;
  if (
    raster &&
    isPositiveFinite(raster.pixel_width) &&
    isPositiveFinite(raster.pixel_height)
  ) {
    return { width: raster.pixel_width, height: raster.pixel_height };
  }
  const vector = record.vector;
  if (
    vector &&
    isPositiveFinite(vector.width) &&
    isPositiveFinite(vector.height)
  ) {
    return { width: vector.width, height: vector.height };
  }
  return null;
}

function isPositiveFinite(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

/** `renderAdapter.ts:1022`'s scene rounding, so a fitted box is a number the
 * document can carry rather than a float tail. */
function roundForScene(value: number): number {
  return Math.round(value * 1000) / 1000;
}

/** The allowlist in prose rather than in mime strings — what a user can act on
 * (Task 7's `UNSUPPORTED_PASTE_FILES`, per file). */
function unsupportedTypeRefusal(fileName: string): string {
  return `${fileName} isn't a type we can add — only PNG, JPEG, WebP, and SVG images`;
}

function oversizeRefusal(fileName: string): string {
  return `${fileName} is larger than the 10 MB limit`;
}

/** A record the store took but has not finished processing (or one it failed).
 * Named by LABEL, which is what the asset store shows it as. */
function notReadyRefusal(record: AssetRecord): string {
  return record.status === "pending"
    ? `"${record.label}" is still processing — add it again once it's ready`
    : `"${record.label}" isn't available (${record.status})`;
}

function messageOf(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

export interface UseSceneImagePasteOptions {
  applyOps: (operations: Operation[], intent?: string) => boolean;
  canApply: () => boolean;
  pageId: PageId | null;
  reportError: (message: string) => void;
  scene: Scene | null;
  selectedNodeId: NodeId | null;
  /** Injectable for tests; the platform's BFF upload by default. */
  upload?: (file: File) => Promise<AssetRecord>;
  /** R21: the canvas's live viewport centre in PAGE space, or null when there
   * is no artboard/viewport to ask — in which case the page's own centre is
   * where a pasted picture goes. */
  viewportPageCenter: () => { x: number; y: number } | null;
}

export interface SceneImagePasteBinding {
  /** The canvas drop: the pointer named a page point, so the picture is
   * centred on it (R3, and never into a layout). */
  onDropImageFiles: (files: File[], pagePoint: { x: number; y: number }) => void;
  /** Task 7's `image-files` seam. */
  onExternalImages: (files: File[], rejected: string[]) => void;
  /** Task 7's `svg-markup` seam. */
  onSvgMarkup: (svg: string) => void;
}

/**
 * The thin binding: latest-value deps and three stable handlers. Every rule
 * above this line is a module function, which is what keeps it testable without
 * React (this lane's shipped shape — `use-scene-replace-image.ts`).
 */
export function useSceneImagePaste(
  options: UseSceneImagePasteOptions,
): SceneImagePasteBinding {
  const {
    applyOps,
    canApply,
    pageId,
    reportError,
    scene,
    selectedNodeId,
    upload = uploadWebAsset,
    viewportPageCenter,
  } = options;

  // Latest-value ref, written in a PASSIVE effect and never at render time
  // (this repo's react-hooks rule; the adaptation every hook on this lane
  // made), so the three handlers keep one identity while always reading the
  // current scene, selection and write path.
  const optionsRef = useRef<UseSceneImagePasteOptions>(options);
  useEffect(() => {
    optionsRef.current = {
      applyOps,
      canApply,
      pageId,
      reportError,
      scene,
      selectedNodeId,
      upload,
      viewportPageCenter,
    };
  });

  const ingest = useCallback(
    (files: File[], mode: PastePlacementMode | null, rejected: string[]) => {
      const current = optionsRef.current;
      if (!current.pageId || !mode) {
        // Nothing to place onto. Said out loud when the user actually handed
        // over pictures, because the gesture was theirs and silence reads as a
        // broken editor.
        if (files.length > 0 || rejected.length > 0) {
          current.reportError(NO_PAGE_TO_PLACE_ON);
        }
        return;
      }
      void ingestExternalImages(
        files,
        {
          mode,
          pageId: current.pageId,
          selectedNodeId: current.selectedNodeId,
        },
        {
          applyOps: current.applyOps,
          canApply: current.canApply,
          parentOrigin: parentOriginOf,
          reportError: current.reportError,
          // Re-read at settle time, through the ref — the scene may have moved
          // under the upload.
          scene: () => optionsRef.current.scene,
          upload: current.upload ?? uploadWebAsset,
        },
        rejected,
      );
    },
    [],
  );

  /** R21: where a ⌘V lands — the viewport's centre, or the page's own centre
   * when there is no artboard/viewport to ask. */
  const pasteMode = useCallback((): PastePlacementMode | null => {
    const current = optionsRef.current;
    const center =
      current.viewportPageCenter() ?? pageCenterOf(current.scene, current.pageId);
    return center ? { kind: "viewport-center", center } : null;
  }, []);

  const onExternalImages = useCallback(
    (files: File[], rejected: string[]) => {
      ingest(files, pasteMode(), rejected);
    },
    [ingest, pasteMode],
  );

  const onSvgMarkup = useCallback(
    (svg: string) => {
      ingest([svgMarkupToFile(svg)], pasteMode(), []);
    },
    [ingest, pasteMode],
  );

  const onDropImageFiles = useCallback(
    (files: File[], pagePoint: { x: number; y: number }) => {
      ingest(files, { kind: "drop-point", pagePoint }, []);
    },
    [ingest],
  );

  return { onDropImageFiles, onExternalImages, onSvgMarkup };
}

/** The page's own centre in page space — R21's fallback anchor. */
function pageCenterOf(
  scene: Scene | null,
  pageId: PageId | null,
): { x: number; y: number } | null {
  const page = scene && pageId ? scene.pages[pageId] : null;
  return page
    ? { x: page.size.width / 2, y: page.size.height / 2 }
    : null;
}
