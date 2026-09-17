"use client";

import { useEffect, useRef } from "react";
import { isTypingTarget } from "../adapter/scene-arrange";
import { sceneAssetPassthroughUrl } from "../adapter/scene-canvas-view";
import {
  SCENE_CLIPBOARD_KIND,
  SCENE_CLIPBOARD_MIME,
  encodeClipboardHtml,
  materializeClipboardPayload,
  rasterToPngBlob,
  serializeSubtree,
  type SceneClipboardPayloadV1,
} from "../adapter/scene-clipboard";
import {
  classifyPaste,
  snapshotClipboardData,
} from "../adapter/scene-clipboard-classify";
import {
  planPastePlacement,
  type PastePlacementMode,
} from "../adapter/scene-clipboard-placement";
import { DESIGN_API_BFF_PREFIX } from "../data/design-bff";
import type {
  AssetRecord,
  Node,
  NodeId,
  PageId,
  Scene,
  TextNode,
} from "../engine/scene/contracts";
import { updateTextNode } from "../engine/scene/operations";
import { pageIdForNode } from "../engine/scene/sceneQueries";
import { deleteEdit } from "../engine/scene/structuredEdits";
import { spansVectorForContentEdit } from "../engine/scene/textSpans";
import type { SceneManualEdits } from "./use-scene-manual-edits";

/**
 * Scene clipboard Task 7 — the event wiring. Tasks 1–6 built the whole pure
 * pipeline (serialize → envelope → validate → re-mint → placement →
 * materialize → classify); this is the first file that makes ⌘C / ⌘X / ⌘V / ⌘D
 * real, and it decides nothing those modules already decide.
 *
 * ── WHY THE SESSION COMPOSES IT (ruling R16) ──────────────────────────────
 * The hook registers its OWN window listeners and is composed by
 * `use-scene-editing-session.ts`, directly beside `useSceneArrange` — this
 * lane's shipped precedent (AD4.A: components never reach the engine or the
 * transport, the session composes handler hooks, and `use-scene-arrange.ts`
 * registers its own window keydown). `scene-artifact-canvas.tsx` is not touched.
 *
 * ── SEMANTIC EVENTS, NOT A KEYMAP (research §7) ───────────────────────────
 * Copy, cut and paste come from the browser's own `copy`/`cut`/`paste` events
 * and NEVER from `keydown`. That is not a style choice: only inside those
 * events is `event.clipboardData` live and writable, and only they fire for
 * the menu-bar Edit ▸ Paste, the right-click menu, and every non-⌘V way an OS
 * pastes. ⌘D is the one chord that IS a keydown, because it is ours alone —
 * it never touches the clipboard at all (founder ruling 4).
 *
 * ── EVERYTHING WITH A RULE LIVES OUTSIDE REACT ────────────────────────────
 * The four handlers below are module-level functions over a plain deps object
 * (`createSceneReplaceImageHandler` / `arrangeShortcut` precedent — the runner
 * is `tsx --test` over `.ts` only, so a hook is never component-tested here).
 * What is left in the hook is genuinely untestable-by-design plumbing:
 * latest-value refs and listener registration.
 */

/** The two fields the typing-target rule reads, so a case can be built without
 * a DOM. `HTMLElement` satisfies it structurally. */
export type SceneClipboardTarget = {
  isContentEditable: boolean;
  tagName: string;
};

/** The half of a `ClipboardEvent` these handlers use. */
export interface SceneClipboardEventLike {
  clipboardData: DataTransfer | null;
  preventDefault: () => void;
}

/** The half of a `KeyboardEvent` the ⌘D chord reads. It carries NO
 * `DataTransfer` — which is how the duplicate path is structurally incapable
 * of touching the clipboard. */
export interface SceneDuplicateEventLike {
  altKey: boolean;
  ctrlKey: boolean;
  key: string;
  metaKey: boolean;
  preventDefault: () => void;
  shiftKey: boolean;
}

/**
 * One `ClipboardItem`'s worth of representations, keyed by mime. Values may be
 * PROMISES: the spec lets a `ClipboardItem` be constructed with pending blobs,
 * which is what keeps the write itself synchronous with the copy event (the
 * user-activation window) while the png is still being rasterized.
 */
export type SceneClipboardItem = Record<string, Blob | Promise<Blob>>;

export interface SceneClipboardDeps {
  /** R12: paste/duplicate generations, keyed `${documentId}:${sourceRootId}`.
   * One map per mount, cleared when the document changes. */
  cascade: Map<string, number>;
  documentId: string | null;
  /** R35: how the outbound `image/png` bytes are fetched. Defaults to
   * {@link fetchAssetBytes}; a test injects rather than reaching the network. */
  fetchAssetBytes?: (url: string) => Promise<Blob>;
  /** Task 8's seam. Absent until it lands, and then the refusal below is what
   * the user sees instead — never a silent swallow. */
  onExternalImages?: (files: File[], rejected: string[]) => void;
  /** Task 8's seam for pasted svg markup. */
  onSvgMarkup?: (svg: string) => void;
  pageId: PageId | null;
  /** W2 / founder ruling 3: does THIS workspace hold the asset behind `assetId`?
   *
   * A clipboard payload carries the asset RECORDS it references, so a paste
   * into another document of the same workspace can register what it needs.
   * A record is not an authorization, though — the payload came off an OS
   * clipboard and could have crossed workspaces. The honest gate is the
   * SERVER's own tenancy check, which is what this asks; the default hits the
   * design BFF (see {@link probeAssetInWorkspace}) and a test injects instead
   * of reaching the network. */
  probeAsset?: (assetId: string) => Promise<boolean>;
  /** R35: the Blob→png rasterizer. Defaults to the adapter's
   * {@link rasterToPngBlob}; jsdom can decode no image, so a test injects a
   * recorder instead. */
  rasterToPng?: (source: Blob, mime: string) => Promise<Blob>;
  scene: Scene | null;
  selectedNodeId: NodeId | null;
  /** R27's INJECTION POINT, not a policy seam: the rich-text remap a plain-text
   * paste writes through is the shipped
   * {@link spansVectorForContentEdit} — but an ESM live binding cannot be
   * replaced from a test, so it rides here and defaults to that same import.
   * Production never sets it. */
  spansVectorForContentEdit?: typeof spansVectorForContentEdit;
  /** R29/R21: the canvas's live viewport centre in PAGE space, or null when
   * there is no viewport serving this document to ask. A minted text node is
   * centred on it, and on the page's own centre when it answers null. */
  viewportPageCenter?: () => { x: number; y: number } | null;
  /** Display/debug only, stamped onto a copied payload. NEVER an auth claim —
   * asset resolution against the pasting workspace is the real gate. */
  workspaceId: string | null;
  /** R35: the async clipboard writer, the ONLY carrier an `image/png` can ride
   * (an event's `setData` takes strings). Defaults to
   * `navigator.clipboard.write` wrapped in `ClipboardItem`s, and stays
   * UNDEFINED where either is missing — the async step is then skipped whole,
   * which is exactly the shipped sync copy. */
  writeClipboardItems?: (items: SceneClipboardItem[]) => Promise<void>;
  writes: Pick<
    SceneManualEdits,
    "applyEdit" | "applyOps" | "canApply" | "reportError"
  >;
}

/** R17: `canApply` is the edit-mode proxy this seam has — the arrange
 * precedent. Its two silent refusals (nothing armed; the engine is D9
 * read-only) are exactly why it is asked up front rather than discovered. */
export const NOT_ACCEPTING_EDITS =
  "This document isn't accepting edits right now.";

/** The copy path's one refusal: the payload cleared 1 MiB, so the `text/html`
 * envelope — the carrier that survives the OS clipboard into other apps — was
 * not written. The internal mime and the plain text still were, so this is a
 * REDUCED copy, not a failed one, and the message says which half was lost. */
const ENVELOPE_TOO_LARGE =
  "This selection is over the 1 MiB clipboard limit — it will paste in this browser, but not into another app.";

/** R9: a files-bearing paste whose files are ALL disallowed. It never quietly
 * becomes a text paste — the human dropped pictures and must hear why none of
 * them landed. (The allowlist is `ALLOWED_IMAGE_MIMES`; the sentence names it
 * in prose rather than in mime strings, which is what a user can act on.) */
const UNSUPPORTED_PASTE_FILES =
  "Only PNG, JPEG, WebP, and SVG images can be pasted.";

/** The default that Task 8 replaces. Stated out loud rather than swallowed:
 * the paste was ours (we `preventDefault`ed it), so silence would look like a
 * broken editor. */
const IMAGE_PASTE_UNAVAILABLE = "Pasting images isn't available yet.";

const PASTE_INTENT = "clipboard.paste";
const DUPLICATE_INTENT = "clipboard.duplicate";
/** Task 9's undo frame: replacing a text node's content and minting a new text
 * node are the same gesture to the user, so they share one label. */
const PASTE_TEXT_INTENT = "clipboard.paste-text";

/**
 * Is this event OURS? Armed (a document, a scene and a page — see
 * {@link armSession}) and not aimed at something that types. The overlay
 * textarea and every inspector field keep their native clipboard, which is the
 * ⌘Z / ⌘G rule verbatim (`scene-arrange.ts::isTypingTarget`, the single copy).
 */
export function shouldOwnClipboardEvent(
  target: SceneClipboardTarget | null,
  armed: boolean,
): boolean {
  return armed && !isTypingTarget(target);
}

/**
 * The three representations a copy writes, and the only place their contents
 * are decided.
 *
 * `internal` is the fast path — same tab, same app, no base64 round trip.
 * `html` is the Figma-style envelope that survives an OS clipboard, or null
 * when the payload is over the 1 MiB cap (the codec refuses rather than
 * truncates). `plain` is the READABLE text, never the JSON: pasting a scene
 * into a chat box must produce the words, which is the Excalidraw Safari-leak
 * lesson stated in the DTO.
 */
export function buildCopyRepresentations(payload: SceneClipboardPayloadV1): {
  internal: string;
  html: string | null;
  plain: string;
} {
  return {
    internal: JSON.stringify(payload),
    html: encodeClipboardHtml(payload),
    plain: payload.readableText,
  };
}

/** An armed session: the three ids that must all exist, plus the selection
 * AFTER R11's cross-page hygiene. */
interface ArmedSession {
  documentId: string;
  pageId: PageId;
  scene: Scene;
  /** The selection ONLY when it lives on the page the session is showing — a
   * node on another page would otherwise be serialized against bounds it does
   * not have, and would be planned into a page it is not on. */
  selectedNodeId: NodeId | null;
}

function armSession(deps: SceneClipboardDeps): ArmedSession | null {
  const { documentId, pageId, scene } = deps;
  // A pageless scene (`open_design_leg@4` births one; the agent authors the
  // first page later) is NOT armed: there is nowhere to copy from or paste to.
  if (!documentId || !scene || !pageId) {
    return null;
  }
  const selectedNodeId =
    deps.selectedNodeId !== null &&
    pageIdForNode(scene, deps.selectedNodeId) === pageId
      ? deps.selectedNodeId
      : null;
  return { documentId, pageId, scene, selectedNodeId };
}

/**
 * Does the DOM say the user has TEXT selected right now?
 *
 * The canvas is CanvasKit — it hosts no DOM text at all — so a non-collapsed
 * selection can only belong to the shell around it: a chat message, a layer
 * label, an artifact title. Copying the selected NODE over that would steal
 * the user's copy, and cutting would additionally delete something they never
 * aimed at. A collapsed selection (a bare caret) is not a selection, and a
 * document-less runtime (node:test, SSR) trivially has none.
 */
function hasDomTextSelection(): boolean {
  if (typeof document === "undefined") {
    return false;
  }
  const selection = document.getSelection?.();
  return selection != null && !selection.isCollapsed;
}

/** The armed session this event belongs to, or null when the event is simply
 * not ours — nothing armed, or a target that types. Every handler starts here,
 * so the two halves of "is this ours" are asked in exactly one place. */
function ownedSession(
  deps: SceneClipboardDeps,
  target: SceneClipboardTarget | null,
): ArmedSession | null {
  const session = armSession(deps);
  return shouldOwnClipboardEvent(target, session !== null) ? session : null;
}

/**
 * R10 — THE F9 TRAP, and the reason this adapter is written here rather than
 * reached for from `sceneQueries`.
 *
 * The planner rebases its page-space target through the PARENT container's
 * origin, so it needs "where does this container sit in page space", keyed by
 * the parent's id. `sceneQueries.parentComputedOrigin(scene, childId)` answers
 * a different question — it is CHILD-keyed — and a pasted node has no child id
 * yet, because it does not exist in the scene. Passing the child-keyed one
 * would silently return (0,0) for the parent and reproduce F9 exactly: a
 * page-absolute number written into a parent-relative transform.
 */
export function parentOriginOf(scene: Scene) {
  return (parentId: NodeId): { x: number; y: number } => {
    const bounds = scene.nodes[parentId]?.computed?.layout_bounds;
    return bounds ? { x: bounds.x, y: bounds.y } : { x: 0, y: 0 };
  };
}

/**
 * Place, materialize and apply ONE batch — the single code path behind ⌘V's
 * internal fast path, ⌘D, and Task 9's minted text node. They differ in
 * exactly two things: where the payload came from, and WHERE it lands, which
 * is the placement mode passed in.
 *
 * ONE `applyOps` call is ONE undo frame; a refusal applies nothing at all
 * (the materializer decides every refusal before it builds its first op, so
 * atomicity is by construction, not by rollback). Returns whether the write
 * path took the batch, which is what the cascade bookkeeping above it reads.
 */
function placeAndApply(
  deps: SceneClipboardDeps,
  session: ArmedSession,
  payload: SceneClipboardPayloadV1,
  mode: PastePlacementMode,
  intent: string,
): boolean {
  const placement = planPastePlacement({
    mode,
    pageId: session.pageId,
    parentComputedOrigin: parentOriginOf(session.scene),
    payloadBounds: payload.bounds,
    scene: session.scene,
    selectedNodeId: session.selectedNodeId,
  });
  const materialized = materializeClipboardPayload(
    session.scene,
    payload,
    placement,
    new Set(Object.keys(session.scene.assets)),
  );
  if ("refusal" in materialized) {
    deps.writes.reportError(materialized.refusal);
    return false;
  }
  return deps.writes.applyOps(materialized.ops, intent);
}

/** {@link placeAndApply} under the R12 cascade: the ⌘V / ⌘D shape, where a
 * repeat placement of the SAME source steps clear of the last one. */
function cascadeAndApply(
  deps: SceneClipboardDeps,
  session: ArmedSession,
  payload: SceneClipboardPayloadV1,
  sourceRootId: NodeId,
  intent: string,
): void {
  const key = `${session.documentId}:${sourceRootId}`;
  // R12: first placement of a given source is generation 1 — one cascade step
  // off the copied box, so a paste is never hidden exactly under its source.
  const generation = (deps.cascade.get(key) ?? 0) + 1;
  // Bumped only on a batch the write path TOOK: a refused paste that advanced
  // the cascade would make the retry land somewhere the user never asked for.
  if (
    placeAndApply(
      deps,
      session,
      payload,
      { generation, kind: "paste-cascade" },
      intent,
    )
  ) {
    deps.cascade.set(key, generation);
  }
}

// ── W2: cross-document assets and the server's tenancy gate ───────────────

/** The refusal a failed tenancy probe speaks — the materializer's own sentence
 * for the same fact, so the user hears one answer however the paste was
 * refused. */
function foreignWorkspaceRefusal(count: number): string {
  return (
    `${count} image${count === 1 ? "" : "s"} in this clipboard ` +
    `${count === 1 ? "belongs" : "belong"} to another workspace`
  );
}

/** The payload's asset records this DOCUMENT does not already hold.
 *
 * `scene.assets` is per-document while assets are workspace-scoped, so this is
 * "what would have to be registered here", NEVER "what this workspace is
 * missing" — the live walk's defect was reading the first as the second. */
function foreignAssetRecords(
  scene: Scene,
  payload: SceneClipboardPayloadV1,
): AssetRecord[] {
  return payload.assets.filter((record) => !(record.id in scene.assets));
}

/**
 * The one asynchronous paste path (founder ruling 3), and the Task-8 ingestion
 * hook's shape verbatim: ask first, re-gate after, then ONE batch.
 *
 * WHY ASK AT ALL. The payload carries records, and a record is a description,
 * not a permission — the clipboard it rode may have come from another
 * workspace's tab entirely. `workspaceHint` cannot answer that (it is
 * display-only, and forgeable), and neither can the target document's asset
 * map. The server's tenancy gate can, so it is asked, once per foreign record.
 *
 * FAIL CLOSED. A probe that answers false OR REJECTS (offline, a 500, a
 * cancelled request) counts as a no: an unverified asset must not be
 * registered into this workspace's document. All-or-nothing, too — a paste
 * that dropped the refused half would silently mutilate the copied subtree.
 *
 * RE-READ, THEN RE-GATE. The scene can change while the probes travel (the
 * deps object is the hook's latest-value ref), so the paste is planned against
 * the CURRENT session and the write gate is asked again — the same re-gate
 * `ingestExternalImages` does after its uploads.
 */
async function pasteWithForeignAssets(
  deps: SceneClipboardDeps,
  payload: SceneClipboardPayloadV1,
  foreign: readonly AssetRecord[],
): Promise<void> {
  const probe = deps.probeAsset ?? probeAssetInWorkspace;
  const verdicts = await Promise.all(
    foreign.map(async (record) => {
      try {
        return await probe(record.id);
      } catch {
        return false;
      }
    }),
  );
  const refused = verdicts.filter((held) => !held).length;
  if (refused > 0) {
    deps.writes.reportError(foreignWorkspaceRefusal(refused));
    return;
  }
  const session = armSession(deps);
  if (!session) {
    // The document closed while we asked. Nothing to paste into, and nothing
    // to say about a gesture whose surface is gone.
    return;
  }
  if (!deps.writes.canApply()) {
    deps.writes.reportError(NOT_ACCEPTING_EDITS);
    return;
  }
  cascadeAndApply(deps, session, payload, payload.roots[0], PASTE_INTENT);
}

/** The production probe: the design BFF's own asset read, whose 404/403 IS the
 * workspace boundary. Only `ok` is read — the body is the server's business. */
async function probeAssetInWorkspace(assetId: string): Promise<boolean> {
  const response = await fetch(
    `${DESIGN_API_BFF_PREFIX}/assets/${encodeURIComponent(assetId)}`,
  );
  return response.ok;
}

// ── Task 9: plain text ─────────────────────────────────────────────────────

/**
 * R28's minted node, stated once. Every number here is a fixed literal rather
 * than a brand-kit read: this hook has no kit, and a deterministic fallback the
 * user can immediately restyle beats a guess dressed up as a theme.
 */
const PASTED_TEXT_ID = "pasted-text";
const PASTED_TEXT_NAME = "Pasted text";
const PASTED_TEXT_FONT_FAMILY = "Inter";
const PASTED_TEXT_FONT_SIZE = 16;
const PASTED_TEXT_LINE_HEIGHT = 1.35;
/** The same 60%-of-the-page's-SHORT-side box a pasted picture is fitted into
 * (`use-scene-image-paste.ts`'s R25), so the two paste gestures agree on what
 * "comfortably inside this page" means. */
const PASTED_TEXT_WIDTH_FRACTION = 0.6;

/**
 * ⌘V of plain text — the two shapes it takes, and the ONE `applyOps` behind
 * both (R26: plain text is ours, not a seam).
 *
 * REPLACE, when a text node is selected and unlocked: the user pointed at a
 * text node and pasted words into it, which is a content edit. The spans go
 * through the shipped rich-text machinery ({@link spansVectorForContentEdit}),
 * never a raw spread — that function owns what happens to a two-colour
 * headline whose content is replaced wholesale, and re-deriving it here would
 * be a second, quietly different answer.
 *
 * MINT, for everything else — an image, a shape, a group, a LOCKED text node,
 * or nothing at all. A locked node is not a paste target for the same reason
 * the placement planner refuses to reach inside one: the human said "don't
 * reason about this". The new node rides the SAME pipeline an internal paste
 * does (plan → materialize → apply), so it is re-minted, inserted childless,
 * and placed by the R2 ladder — including into an auto-layout row when one is
 * selected (founder ruling 2).
 */
function pasteText(
  deps: SceneClipboardDeps,
  session: ArmedSession,
  text: string,
): void {
  const selected = session.selectedNodeId
    ? session.scene.nodes[session.selectedNodeId]
    : null;
  if (selected && selected.kind.kind === "text" && !selected.locked) {
    // The STORED node is what the remap reads (its `content` and `spans` are
    // the document's); `text` is what is being written.
    const stored: TextNode = selected.kind;
    const spansFor = deps.spansVectorForContentEdit ?? spansVectorForContentEdit;
    const spans = spansFor(stored, text, stored.spans ?? []);
    deps.writes.applyOps(
      [updateTextNode(selected, { content: text, spans })],
      PASTE_TEXT_INTENT,
    );
    return;
  }
  const page = session.scene.pages[session.pageId] ?? null;
  if (!page) {
    // A pageId naming no page is a scene-invariant violation, not this
    // handler's to repair — and it cannot arrive from the session, which reads
    // both from the same loaded document. There is simply nowhere to place a
    // node, so nothing is placed; a throw out of a window listener would be
    // the worse answer.
    return;
  }
  const width = Math.round(
    PASTED_TEXT_WIDTH_FRACTION * Math.min(page.size.width, page.size.height),
  );
  const center = deps.viewportPageCenter?.() ?? {
    x: page.size.width / 2,
    y: page.size.height / 2,
  };
  placeAndApply(
    deps,
    session,
    pastedTextPayload(text, width),
    { center, kind: "viewport-center" },
    PASTE_TEXT_INTENT,
  );
}

/**
 * The pasted text as a one-node clipboard payload, so it reaches the scene
 * through the same materializer every other paste does rather than through a
 * second, hand-rolled insert path.
 *
 * `bounds` exists ONLY to centre the box: the width is real, and the height is
 * a line-count estimate at the node's own line height — the solver owns the
 * hug height it actually lays out at, and nothing downstream reads this number
 * again.
 */
function pastedTextPayload(
  text: string,
  width: number,
): SceneClipboardPayloadV1 {
  const lines = text.split("\n").length;
  return {
    kind: SCENE_CLIPBOARD_KIND,
    version: 1,
    workspaceHint: null,
    roots: [PASTED_TEXT_ID],
    nodes: [pastedTextNode(text, width)],
    assetIds: [],
    // A minted text node references no picture, so there is nothing to carry
    // and nothing to register.
    assets: [],
    bounds: {
      x: 0,
      y: 0,
      width,
      height: Math.ceil(lines * PASTED_TEXT_FONT_SIZE * PASTED_TEXT_LINE_HEIGHT),
    },
    readableText: text,
  };
}

/**
 * R28's literal. The id is a PLACEHOLDER — `materializeClipboardPayload`
 * re-mints it against the scene, so this node never reaches a document under
 * it.
 *
 * Fixed width / hug height is the harvested ad's own shape for a text node
 * (`text_headline`, `text_proof_stat`), and the single fill is not cosmetic: a
 * text node with EMPTY fills paints nothing at all, so a fill-less mint would
 * be an invisible paste.
 */
function pastedTextNode(text: string, width: number): Node {
  return {
    id: PASTED_TEXT_ID,
    name: PASTED_TEXT_NAME,
    kind: {
      kind: "text",
      content: text,
      font_family: PASTED_TEXT_FONT_FAMILY,
      font_size: PASTED_TEXT_FONT_SIZE,
      font_weight: 400,
      align: "left",
      wrap: "wrap",
      direction: "ltr",
      line_height: PASTED_TEXT_LINE_HEIGHT,
      letter_spacing: 0,
    },
    transform: {
      x: 0,
      y: 0,
      rotation: 0,
      skew_x: 0,
      skew_y: 0,
      flip_x: false,
      flip_y: false,
    },
    size: { width: { kind: "fixed", value: width }, height: { kind: "hug" } },
    children: [],
    fills: [
      {
        id: "paint_pasted_text",
        paint: { kind: "solid", color: { kind: "hex", value: "#111111" } },
      },
    ],
    strokes: [],
    corner: { top_left: 0, top_right: 0, bottom_right: 0, bottom_left: 0 },
    opacity: 1,
    clip: false,
    layout: null,
    // The engine's to solve, never ours to author (R8).
    computed: null,
    locked: false,
  };
}

/** Serialize the current selection and stamp the workspace hint, or null when
 * there is nothing to copy. */
function copyPayload(
  deps: SceneClipboardDeps,
  session: ArmedSession,
): SceneClipboardPayloadV1 | null {
  if (!session.selectedNodeId) {
    return null;
  }
  const payload = serializeSubtree(
    session.scene,
    session.pageId,
    session.selectedNodeId,
  );
  return payload
    ? { ...payload, workspaceHint: deps.workspaceId ?? null }
    : null;
}

/**
 * The shared body of ⌘C and ⌘X: write the three representations, or leave the
 * event completely alone.
 *
 * Returns the root id it copied, which is what cut then deletes — so a cut can
 * never delete something the clipboard did not receive.
 *
 * NOTHING SELECTED IS NOT A FAILURE. The event is left untouched (no
 * `preventDefault`, no message) so the browser's own copy — selected text in
 * view mode, say — still happens. A copy that cannot be ours must not become a
 * copy that is nobody's.
 */
function writeCopy(
  deps: SceneClipboardDeps,
  session: ArmedSession,
  event: SceneClipboardEventLike,
): NodeId | null {
  const data = event.clipboardData;
  if (!data) {
    return null;
  }
  const payload = copyPayload(deps, session);
  if (!payload) {
    return null;
  }
  const representations = buildCopyRepresentations(payload);
  event.preventDefault();
  data.setData(SCENE_CLIPBOARD_MIME, representations.internal);
  data.setData("text/plain", representations.plain);
  if (representations.html !== null) {
    data.setData("text/html", representations.html);
  } else {
    deps.writes.reportError(ENVELOPE_TOO_LARGE);
  }
  // Task 10, and strictly AFTER the three writes above (R31): everything the
  // editor itself needs is already on the clipboard, so whatever happens next
  // can only ADD.
  offerImagePng(deps, session, payload, representations);
  return payload.roots[0];
}

// ── Task 10: the outbound picture (founder ruling 4 / R31–R35) ─────────────

/**
 * A copied IMAGE node, offered to OTHER apps as a real picture.
 *
 * WHY THERE IS A SECOND WRITE AT ALL. Preview, Slack and Keynote understand
 * one thing: `image/png` bytes. A copy event's `setData` takes STRINGS only,
 * so the picture can leave this app only through `navigator.clipboard.write`
 * — a different, async, permissioned API. Hence both: the sync trio above is
 * the copy, and this is a best-effort enrichment of it.
 *
 * EVERY FAILURE IS SWALLOWED, on purpose. Denied permission, no user
 * activation, a browser that rejects promise-valued items, a 404 on the asset
 * bytes, a decode the canvas cannot do — none of them may cost the user the
 * copy they already have, and none of them is worth a message about a
 * representation they never asked for. `reportError` is deliberately not
 * called here; the sync path owns the one sentence this gesture can say.
 *
 * THE KNOWN COST, ledgered rather than hidden: when the async write SUCCEEDS
 * the browser replaces the clipboard with this item's three types, so the
 * custom `SCENE_CLIPBOARD_MIME` fast path is gone for that copy. Custom mimes
 * cannot ride a `ClipboardItem` (the browser's type allowlist), so this is
 * unavoidable — and harmless: the `text/html` envelope carries the identical
 * payload, and an internal paste classifies off it via `decodeClipboardHtml`.
 * That is also why an over-cap copy (`html === null`) skips the write
 * entirely: trading a complete clipboard for a picture would be a real loss.
 *
 * SCOPE IS THE ROOT'S KIND (ruling 4): only an image node. A text, shape,
 * vector or group root already travels as `text/plain` + `text/html`, and
 * flattening a group to a bitmap here would be a rendering decision this file
 * has no business making.
 */
function offerImagePng(
  deps: SceneClipboardDeps,
  session: ArmedSession,
  payload: SceneClipboardPayloadV1,
  representations: { html: string | null; plain: string },
): void {
  const html = representations.html;
  const root = payload.nodes[0];
  if (html === null || !root || root.kind.kind !== "image") {
    return;
  }
  const write = deps.writeClipboardItems ?? defaultClipboardItemWriter();
  if (!write) {
    return;
  }
  const png = imagePngBlob(deps, session.scene, root.kind.asset_id);
  // The item consumes this same promise; this lone handler only keeps a
  // rejection from surfacing as an unhandled one when the write itself has
  // already failed for another reason.
  png.catch(() => {});
  // SYNCHRONOUS inside the copy event — the png is still pending, and that is
  // the point: waiting for bytes would land the call outside the activation
  // window, where every browser refuses it. Which is also why this is a
  // try/catch and not a deferring `Promise.resolve().then(...)`: R31 swallows
  // BOTH failure shapes, but only one of them may be bought by leaving the
  // activation tick.
  //
  // THE SYNCHRONOUS THROW IS REAL, not defensive padding: the default writer
  // constructs `ClipboardItem`s in its own synchronous prefix, and that
  // constructor throws a TypeError in engines that do not accept
  // promise-valued entries (Firefox). An exception escaping here would leave a
  // window `copy` listener throwing — and would abort `handleSceneClipboardCut`
  // BEFORE its delete, turning a cut into a copy that never removed anything.
  try {
    write([
      {
        "image/png": png,
        "text/html": new Blob([html], { type: "text/html" }),
        "text/plain": new Blob([representations.plain], { type: "text/plain" }),
      },
    ]).catch(() => {});
  } catch {
    // The enrichment failed before it began. The baseline copy stands, and it
    // is the whole copy — so there is nothing to say and nothing to undo.
  }
}

/** The copied image node's bytes, as png. Rejects — never resolves a
 * placeholder — when the asset has no usable digest, the fetch fails, the
 * mime cannot be determined, or the rasterizer cannot decode (R33). */
async function imagePngBlob(
  deps: SceneClipboardDeps,
  scene: Scene,
  assetId: string,
): Promise<Blob> {
  // The scene's OWN resolver — the same passthrough URL the canvas fetches
  // through. Never a hand-built asset URL: the prefix/`new URL` trap is
  // documented at its definition, and a record with no usable digest must
  // answer null rather than a URL that can only 404.
  const url = sceneAssetPassthroughUrl(scene.assets, assetId);
  if (!url) {
    throw new Error("copied image asset has no fetchable digest");
  }
  const bytes = await (deps.fetchAssetBytes ?? fetchAssetBytes)(url);
  const record = scene.assets?.[assetId];
  // R33's order: the record's declared mime, then "it is a vector record, so
  // it is svg", then whatever the response labelled the bytes. An empty answer
  // is a refusal, not a default — guessing png over jpeg bytes would produce a
  // clipboard picture no app can open.
  const mime =
    record?.media?.mime_type || (record?.vector ? "image/svg+xml" : bytes.type);
  if (!mime) {
    throw new Error("copied image asset has no known mime type");
  }
  // A png needs no rasterizing at all — its bytes ARE the representation, so
  // the copy path never schedules a decode it does not need. (The adapter's
  // own png branch answers the same way for any other caller.)
  if (mime === "image/png") {
    return bytes;
  }
  return await (deps.rasterToPng ?? rasterToPngBlob)(bytes, mime);
}

/** The production `image/png` fetch: the digest passthrough, checked. A non-ok
 * response is a rejection, never an html error page handed to the clipboard as
 * if it were pixels. */
async function fetchAssetBytes(url: string): Promise<Blob> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`asset bytes unavailable (${response.status})`);
  }
  return await response.blob();
}

/**
 * The real async writer, or UNDEFINED where the browser has no async clipboard
 * (older Safari/Firefox, jsdom, SSR). Undefined is a first-class answer: the
 * copy is then exactly the shipped sync one, with nothing logged and nothing
 * refused.
 */
function defaultClipboardItemWriter():
  | ((items: SceneClipboardItem[]) => Promise<void>)
  | undefined {
  if (
    typeof ClipboardItem === "undefined" ||
    typeof navigator === "undefined" ||
    typeof navigator.clipboard?.write !== "function"
  ) {
    return undefined;
  }
  return (items) =>
    navigator.clipboard.write(items.map((item) => new ClipboardItem(item)));
}

/**
 * ⌘C / Edit ▸ Copy / right-click Copy. A read, so it asks no write gate.
 *
 * It yields to a live DOM text selection: the brief's own rule is that the
 * browser's copy of selected text must survive, and a node selection left over
 * from an earlier click must not out-rank the words the user just highlighted.
 */
export function handleSceneClipboardCopy(
  deps: SceneClipboardDeps,
  event: SceneClipboardEventLike,
  target: SceneClipboardTarget | null,
): void {
  const session = ownedSession(deps, target);
  if (!session || hasDomTextSelection()) {
    return;
  }
  writeCopy(deps, session, event);
}

/**
 * ⌘X — the copy, then the delete.
 *
 * The delete is the SHIPPED structured-edit path (`deleteEdit` →
 * `writes.applyEdit`), which is already the undo frame; re-deriving "which
 * removals make a cut" here would be the fabrication this lane avoids by
 * applying only the engine's own operations.
 *
 * The write gate is asked FIRST, before anything is copied: a cut is a write,
 * and a document that cannot take the delete must not be left having copied
 * (the user would then paste and wonder where the original went).
 *
 * It yields to a live DOM text selection for copy's reason and one worse: a
 * cut aimed at highlighted shell text would delete a node the user never
 * pointed at. The yield is asked BEFORE the write gate, so a non-event stays a
 * complete non-event — no message either.
 */
export function handleSceneClipboardCut(
  deps: SceneClipboardDeps,
  event: SceneClipboardEventLike,
  target: SceneClipboardTarget | null,
): void {
  const session = ownedSession(deps, target);
  if (!session || hasDomTextSelection()) {
    return;
  }
  if (!deps.writes.canApply()) {
    deps.writes.reportError(NOT_ACCEPTING_EDITS);
    return;
  }
  const copiedRootId = writeCopy(deps, session, event);
  if (!copiedRootId) {
    return;
  }
  deps.writes.applyEdit(deleteEdit({ id: copiedRootId, kind: "node" }));
}

/**
 * ⌘V / Edit ▸ Paste / right-click Paste — five classes, one decided shape.
 *
 * THE SNAPSHOT IS FIRST AND SYNCHRONOUS. A `DataTransfer` is dead after any
 * async boundary (the Firefox lesson: one `await` and `files` is empty and
 * `getData` returns ""), so everything it carries is copied into plain data
 * inside the event's own turn, before a single decision is made.
 *
 * THE WRITE GATE SITS AFTER THE CLASSIFICATION, not before it, so that an
 * EMPTY clipboard stays the complete non-event both rulings ask for (intent
 * `none` → nothing, no `preventDefault`) instead of producing a read-only
 * complaint about a paste that was never going to write anything.
 *
 * EXACTLY ONE BRANCH EVER WAITS (W2): an internal payload carrying asset
 * records this document does not hold, which the server's tenancy gate must
 * answer for before anything is applied. Everything the event itself owns —
 * the snapshot, the classification, `preventDefault` — has already happened by
 * then, so that branch is fire-and-forget from the listener's point of view;
 * every other paste, including every same-document one, stays synchronous.
 */
export function handleSceneClipboardPaste(
  deps: SceneClipboardDeps,
  event: SceneClipboardEventLike,
  target: SceneClipboardTarget | null,
): void {
  const session = ownedSession(deps, target);
  if (!session) {
    return;
  }
  const data = event.clipboardData;
  if (!data) {
    return;
  }
  const snapshot = snapshotClipboardData(data);
  const intent = classifyPaste(snapshot);
  // R9: files rode along, and the classifier fell PAST the image class — so
  // none of them is a type we accept. A files-bearing paste never silently
  // becomes a text paste OR A NON-EVENT, which is why this is computed from
  // the SNAPSHOT and decided before any other class — including `none`, which
  // is exactly what a clipboard holding only a GIF classifies as (no text, no
  // html, no internal carrier, nothing allowed among the files). Answering
  // that with silence would read as a broken editor. (An internal payload
  // still wins: envelope-beats-files is the classifier's own pinned contract.)
  const refusedFiles =
    snapshot.files.length > 0 &&
    intent.kind !== "image-files" &&
    intent.kind !== "internal";
  if (!refusedFiles && intent.kind === "none") {
    return;
  }
  if (!deps.writes.canApply()) {
    // PRECEDENCE: the read-only sentence outranks the allowlist one. Naming
    // the allowlist here would mislead — an allowed PNG would not have pasted
    // either — so the honest answer is the state that actually refused.
    // The event is still CLAIMED when files rode along: we spoke about it, so
    // the browser must not also act on it.
    if (snapshot.files.length > 0) {
      event.preventDefault();
    }
    deps.writes.reportError(NOT_ACCEPTING_EDITS);
    return;
  }

  if (intent.kind === "internal") {
    // Ours, decided synchronously — `preventDefault` may never wait on a
    // network answer, and the DataTransfer is already snapshotted above.
    event.preventDefault();
    const foreign = foreignAssetRecords(session.scene, intent.payload);
    if (foreign.length === 0) {
      // The whole shipped fast path, unchanged: same-document pastes, ⌘D's
      // twin, and every asset-free subtree stay fully SYNCHRONOUS — no probe,
      // no await, one batch inside the event's own turn.
      cascadeAndApply(
        deps,
        session,
        intent.payload,
        intent.payload.roots[0],
        PASTE_INTENT,
      );
      return;
    }
    // W2: the payload wants to register records this document has never seen.
    // The server decides whether this workspace may have them.
    void pasteWithForeignAssets(deps, intent.payload, foreign);
    return;
  }
  if (refusedFiles) {
    event.preventDefault();
    deps.writes.reportError(UNSUPPORTED_PASTE_FILES);
    return;
  }

  switch (intent.kind) {
    case "image-files":
      event.preventDefault();
      if (deps.onExternalImages) {
        deps.onExternalImages(intent.files, intent.rejected);
      } else {
        deps.writes.reportError(IMAGE_PASTE_UNAVAILABLE);
      }
      return;
    case "svg-markup":
      event.preventDefault();
      if (deps.onSvgMarkup) {
        deps.onSvgMarkup(intent.svg);
      } else {
        deps.writes.reportError(IMAGE_PASTE_UNAVAILABLE);
      }
      return;
    case "plain-text":
      // R26: ours, natively. The browser's own paste would put these
      // characters nowhere (the canvas hosts no DOM text), so claiming the
      // event is what makes ⌘V mean something here.
      event.preventDefault();
      pasteText(deps, session, intent.text);
      return;
    case "none":
      // Only reachable with `refusedFiles` set, which the branch above already
      // answered — a genuinely empty clipboard returned at the guard.
      return;
    default: {
      // Exhaustiveness: a new intent class must decide its own routing, loudly.
      const unreachable: never = intent;
      throw new Error(`unhandled paste intent: ${JSON.stringify(unreachable)}`);
    }
  }
}

/**
 * ⌘D — the ONE chord this file owns, and the one path that never touches a
 * clipboard (founder ruling 4: the duplicate is an internal fast path, so the
 * user's actual clipboard survives a duplicate).
 *
 * `preventDefault` fires for every armed ⌘D, including the refused ones: the
 * browser's Add-bookmark chord must not open a dialog over the canvas because
 * the document happened to be read-only or nothing was selected.
 */
export function handleSceneClipboardDuplicate(
  deps: SceneClipboardDeps,
  event: SceneDuplicateEventLike,
  target: SceneClipboardTarget | null,
): void {
  if (
    !(event.metaKey || event.ctrlKey) ||
    event.altKey ||
    event.shiftKey ||
    event.key.toLowerCase() !== "d"
  ) {
    return;
  }
  const session = ownedSession(deps, target);
  if (!session) {
    return;
  }
  event.preventDefault();
  if (!deps.writes.canApply()) {
    deps.writes.reportError(NOT_ACCEPTING_EDITS);
    return;
  }
  // The CURRENT SELECTION, serialized fresh — never the OS clipboard, which
  // may hold something else entirely.
  const payload = copyPayload(deps, session);
  if (!payload || !session.selectedNodeId) {
    return;
  }
  cascadeAndApply(
    deps,
    session,
    payload,
    session.selectedNodeId,
    DUPLICATE_INTENT,
  );
}

export interface UseSceneClipboardOptions {
  documentId: string | null;
  onExternalImages?: (files: File[], rejected: string[]) => void;
  onSvgMarkup?: (svg: string) => void;
  pageId: PageId | null;
  scene: Scene | null;
  /** The session's PRIMARY selection (`selectedIds[0] ?? null`). V1 copies one
   * subtree — the shipped selection model's own shape. */
  selectedNodeId: NodeId | null;
  /** R29: the same canvas-viewport centre the image paste takes — where a
   * minted text node lands. */
  viewportPageCenter?: () => { x: number; y: number } | null;
  workspaceId?: string | null;
  writes: SceneClipboardDeps["writes"];
}

/**
 * The registration. Three semantic clipboard listeners and one keydown, armed
 * on the document and torn down with it — the ⌘Z / ⌘G placement rule
 * (`use-scene-arrange.ts`), which is why this hook takes the document id at
 * all.
 */
export function useSceneClipboard(options: UseSceneClipboardOptions): void {
  const {
    documentId,
    onExternalImages,
    onSvgMarkup,
    pageId,
    scene,
    selectedNodeId,
    viewportPageCenter,
    workspaceId = null,
    writes,
  } = options;

  // Latest-value ref so every listener keeps one identity while always reading
  // current state, written in a PASSIVE effect and never at render time (this
  // repo's react-hooks rule; the adaptation every hook on this lane made). The
  // cascade map is created once here and carried forward below, so paste
  // generations survive re-renders.
  const depsRef = useRef<SceneClipboardDeps>({
    cascade: new Map<string, number>(),
    documentId,
    onExternalImages,
    onSvgMarkup,
    pageId,
    scene,
    selectedNodeId,
    viewportPageCenter,
    workspaceId,
    writes,
  });
  useEffect(() => {
    depsRef.current = {
      cascade: depsRef.current.cascade,
      documentId,
      onExternalImages,
      onSvgMarkup,
      pageId,
      scene,
      selectedNodeId,
      viewportPageCenter,
      workspaceId,
      writes,
    };
  });

  useEffect(() => {
    if (!documentId) return;
    // R12: generations belong to a document. The keys are document-scoped too,
    // so this is belt-and-braces — but a map that grows across every artifact a
    // session opens is a leak, and clearing it here is the honest reset.
    depsRef.current.cascade.clear();

    const readTarget = (event: Event): SceneClipboardTarget | null =>
      event.target as SceneClipboardTarget | null;
    const onCopy = (event: ClipboardEvent) => {
      handleSceneClipboardCopy(depsRef.current, event, readTarget(event));
    };
    const onCut = (event: ClipboardEvent) => {
      handleSceneClipboardCut(depsRef.current, event, readTarget(event));
    };
    const onPaste = (event: ClipboardEvent) => {
      handleSceneClipboardPaste(depsRef.current, event, readTarget(event));
    };
    const onKeyDown = (event: KeyboardEvent) => {
      handleSceneClipboardDuplicate(depsRef.current, event, readTarget(event));
    };
    window.addEventListener("copy", onCopy);
    window.addEventListener("cut", onCut);
    window.addEventListener("paste", onPaste);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("copy", onCopy);
      window.removeEventListener("cut", onCut);
      window.removeEventListener("paste", onPaste);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [documentId]);
}
