"use client";

import { useEffect, useRef } from "react";
import { isTypingTarget } from "../adapter/scene-arrange";
import {
  SCENE_CLIPBOARD_MIME,
  encodeClipboardHtml,
  materializeClipboardPayload,
  serializeSubtree,
  type SceneClipboardPayloadV1,
} from "../adapter/scene-clipboard";
import {
  classifyPaste,
  snapshotClipboardData,
} from "../adapter/scene-clipboard-classify";
import { planPastePlacement } from "../adapter/scene-clipboard-placement";
import type { NodeId, PageId, Scene } from "../engine/scene/contracts";
import { pageIdForNode } from "../engine/scene/sceneQueries";
import { deleteEdit } from "../engine/scene/structuredEdits";
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

export interface SceneClipboardDeps {
  /** R12: paste/duplicate generations, keyed `${documentId}:${sourceRootId}`.
   * One map per mount, cleared when the document changes. */
  cascade: Map<string, number>;
  documentId: string | null;
  /** Task 8's seam. Absent until it lands, and then the refusal below is what
   * the user sees instead — never a silent swallow. */
  onExternalImages?: (files: File[], rejected: string[]) => void;
  /** Task 9's seam. Absent until it lands, and while it is absent a plain-text
   * paste stays NATIVE (no `preventDefault`), which is harmless. */
  onPlainText?: (text: string) => void;
  /** Task 8's seam for pasted svg markup. */
  onSvgMarkup?: (svg: string) => void;
  pageId: PageId | null;
  scene: Scene | null;
  selectedNodeId: NodeId | null;
  /** Display/debug only, stamped onto a copied payload. NEVER an auth claim —
   * asset resolution against the pasting workspace is the real gate. */
  workspaceId: string | null;
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
 * Place, materialize and apply ONE batch — the single code path behind both
 * ⌘V's internal fast path and ⌘D, which differ only in where the payload came
 * from and what the cascade is keyed by.
 *
 * ONE `applyOps` call is ONE undo frame; a refusal applies nothing at all
 * (the materializer decides every refusal before it builds its first op, so
 * atomicity is by construction, not by rollback).
 */
function placeAndApply(
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
  const placement = planPastePlacement({
    mode: { generation, kind: "paste-cascade" },
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
    return;
  }
  // Bumped only on a batch the write path TOOK: a refused paste that advanced
  // the cascade would make the retry land somewhere the user never asked for.
  if (deps.writes.applyOps(materialized.ops, intent)) {
    deps.cascade.set(key, generation);
  }
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
  return payload.roots[0];
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
  // Task 9's class is the one that is not ours yet: leaving it native is
  // harmless (the browser pastes nothing into a canvas), while claiming it
  // would make ⌘V feel broken.
  if (!refusedFiles && intent.kind === "plain-text" && !deps.onPlainText) {
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
    event.preventDefault();
    placeAndApply(
      deps,
      session,
      intent.payload,
      intent.payload.roots[0],
      PASTE_INTENT,
    );
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
      // Guarded above: the seam exists, or we never got here.
      event.preventDefault();
      deps.onPlainText?.(intent.text);
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
  placeAndApply(
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
  onPlainText?: (text: string) => void;
  onSvgMarkup?: (svg: string) => void;
  pageId: PageId | null;
  scene: Scene | null;
  /** The session's PRIMARY selection (`selectedIds[0] ?? null`). V1 copies one
   * subtree — the shipped selection model's own shape. */
  selectedNodeId: NodeId | null;
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
    onPlainText,
    onSvgMarkup,
    pageId,
    scene,
    selectedNodeId,
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
    onPlainText,
    onSvgMarkup,
    pageId,
    scene,
    selectedNodeId,
    workspaceId,
    writes,
  });
  useEffect(() => {
    depsRef.current = {
      cascade: depsRef.current.cascade,
      documentId,
      onExternalImages,
      onPlainText,
      onSvgMarkup,
      pageId,
      scene,
      selectedNodeId,
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
