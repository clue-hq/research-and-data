import assert from "node:assert/strict";
import { it, mock } from "node:test";
import { JSDOM } from "jsdom";
import {
  AD_DOCUMENT_ID,
  AD_PAGE_ID,
  HARVESTED_AD_PAGE,
} from "../adapter/__fixtures__/scene-nodes";
import {
  SCENE_CLIPBOARD_MIME,
  encodeClipboardHtml,
  serializeSubtree,
  type SceneClipboardPayloadV1,
} from "../adapter/scene-clipboard";
import { DESIGN_API_BFF_PREFIX } from "../data/design-bff";
import type {
  Node,
  Operation,
  Scene,
  TextNode,
  TextSpan,
} from "../engine/scene/contracts";
import { updateTextNode } from "../engine/scene/operations";
import { deleteEdit, type StructuredEdit } from "../engine/scene/structuredEdits";
import { spansVectorForContentEdit } from "../engine/scene/textSpans";
import {
  buildCopyRepresentations,
  handleSceneClipboardCopy,
  handleSceneClipboardCut,
  handleSceneClipboardDuplicate,
  handleSceneClipboardPaste,
  shouldOwnClipboardEvent,
  type SceneClipboardDeps,
} from "./use-scene-clipboard";

/**
 * Clipboard Task 7 — the event wiring: what a real `copy` / `cut` / `paste`
 * event and the ⌘D chord DO, decided by extracted handlers the hook merely
 * registers (`createSceneReplaceImageHandler` / `arrangeShortcut` precedent —
 * the runner is `tsx --test` over `.ts` only, so a hook is never
 * component-tested here and everything with a rule lives outside React).
 *
 * TWO THINGS JSDOM CANNOT HOST, probed rather than assumed: it implements
 * neither `ClipboardEvent` nor `DataTransfer` (both `undefined` on a fresh
 * `JSDOM("").window`), so every case below drives the handlers with a stub
 * `DataTransfer` whose `getData`/`setData`/`files` are a real map and a real
 * array. The stub is faithful to the two properties the pipeline leans on: a
 * `getData` for an absent type returns `""`, and `setData` is the only way
 * anything reaches the clipboard. The one case that genuinely needs the
 * browser's own event classes is skipped, with its reason recorded at the
 * skip (the web-toolbar precedent).
 *
 * The DOMParser install is the shipped clipboard suites' — `decodeClipboardHtml`
 * (reached by the envelope round-trip below) parses through it.
 */
const DOM = new JSDOM("");
(globalThis as { DOMParser?: unknown }).DOMParser = DOM.window.DOMParser;

// ── harness ────────────────────────────────────────────────────────────────

/** A `DataTransfer` faithful enough for the two things the pipeline does with
 * one: read every representation synchronously, and write three back. */
function stubClipboardData(
  seed: Record<string, string> = {},
  files: File[] = [],
  /** Task 10: the SHARED call log a case passes in when it needs to prove the
   * sync `setData` trio ran BEFORE the async clipboard write was issued
   * (R31's baseline-first rule is an ordering claim, so it needs an order). */
  order: string[] = [],
): {
  data: DataTransfer;
  order: string[];
  reads: string[];
  written: Map<string, string>;
} {
  const held = new Map(Object.entries(seed));
  const written = new Map<string, string>();
  const reads: string[] = [];
  const data = {
    files,
    getData(type: string): string {
      reads.push(type);
      return held.get(type) ?? "";
    },
    setData(type: string, value: string): void {
      order.push(`setData:${type}`);
      written.set(type, value);
      held.set(type, value);
    },
  };
  return { data: data as unknown as DataTransfer, order, reads, written };
}

function clipboardEvent(data: DataTransfer | null): {
  clipboardData: DataTransfer | null;
  preventDefault: () => void;
  prevented: () => number;
} {
  const prevented = mock.fn();
  return {
    clipboardData: data,
    preventDefault: prevented,
    prevented: () => prevented.mock.callCount(),
  };
}

function duplicateEvent(
  overrides: Partial<{
    altKey: boolean;
    ctrlKey: boolean;
    key: string;
    metaKey: boolean;
    shiftKey: boolean;
  }> = {},
): {
  altKey: boolean;
  ctrlKey: boolean;
  key: string;
  metaKey: boolean;
  preventDefault: () => void;
  prevented: () => number;
  shiftKey: boolean;
} {
  const prevented = mock.fn();
  return {
    altKey: false,
    ctrlKey: false,
    key: "d",
    metaKey: true,
    preventDefault: prevented,
    prevented: () => prevented.mock.callCount(),
    shiftKey: false,
    ...overrides,
  };
}

const CANVAS_TARGET = { isContentEditable: false, tagName: "CANVAS" };

function harness(overrides: Partial<SceneClipboardDeps> = {}) {
  const applyEdit = mock.fn<(edit: StructuredEdit) => void>();
  const applyOps = mock.fn<(operations: Operation[], intent?: string) => boolean>(
    () => true,
  );
  const canApply = mock.fn(() => true);
  const reportError = mock.fn<(message: string) => void>();
  const deps: SceneClipboardDeps = {
    cascade: new Map<string, number>(),
    documentId: AD_DOCUMENT_ID,
    pageId: AD_PAGE_ID,
    scene: HARVESTED_AD_PAGE,
    selectedNodeId: "group_proof",
    workspaceId: null,
    writes: { applyEdit, applyOps, canApply, reportError },
    ...overrides,
  };
  return { applyEdit, applyOps, canApply, deps, reportError };
}

function clone(scene: Scene): Scene {
  return structuredClone(scene);
}

const GROUP_PAYLOAD = serializeSubtree(HARVESTED_AD_PAGE, AD_PAGE_ID, "group_proof")!;
const HEADLINE_PAYLOAD = serializeSubtree(HARVESTED_AD_PAGE, AD_PAGE_ID, "text_headline")!;

/** The transform the one applied batch gives the pasted ROOT — the first op is
 * the root's insert (parents-first preorder), so its node's transform is what
 * the cascade moved. */
function rootTransformOf(operations: Operation[]): { x: number; y: number } {
  const first = operations[0] as unknown as { node: Node };
  return { x: first.node.transform.x, y: first.node.transform.y };
}

// ── shouldOwnClipboardEvent ────────────────────────────────────────────────

it("refuses every typing target — a focused field keeps its native clipboard", () => {
  for (const target of [
    { isContentEditable: false, tagName: "INPUT" },
    { isContentEditable: false, tagName: "TEXTAREA" },
    { isContentEditable: true, tagName: "DIV" },
  ]) {
    assert.equal(shouldOwnClipboardEvent(target, true), false);
  }
  assert.equal(shouldOwnClipboardEvent(CANVAS_TARGET, true), true);
  assert.equal(shouldOwnClipboardEvent(null, true), true);
});

it("refuses an unarmed session — no document, no scene, no page", () => {
  assert.equal(shouldOwnClipboardEvent(CANVAS_TARGET, false), false);
  assert.equal(shouldOwnClipboardEvent(null, false), false);
});

// ── buildCopyRepresentations ───────────────────────────────────────────────

it("builds all three representations — plain text is READABLE, never the JSON", () => {
  const reps = buildCopyRepresentations(GROUP_PAYLOAD);
  assert.equal(reps.internal, JSON.stringify(GROUP_PAYLOAD));
  assert.equal(reps.html, encodeClipboardHtml(GROUP_PAYLOAD));
  assert.equal(reps.plain, GROUP_PAYLOAD.readableText);
  // The Excalidraw Safari-leak lesson: a human pasting into a text field must
  // get the text, not a wall of JSON.
  assert.ok(!reps.plain.startsWith("{"));
  assert.ok(reps.plain.length > 0);
});

it("drops ONLY the html envelope at the 1 MiB cap — internal and plain survive", () => {
  const oversized: SceneClipboardPayloadV1 = {
    ...GROUP_PAYLOAD,
    readableText: "x".repeat(1_048_577),
  };
  const reps = buildCopyRepresentations(oversized);
  assert.equal(reps.html, null);
  assert.ok(reps.internal.length > 1_048_576);
  assert.equal(reps.plain, oversized.readableText);
});

// ── copy ───────────────────────────────────────────────────────────────────

it("copy writes all three representations and stamps the workspace hint", () => {
  const { deps, reportError } = harness({ workspaceId: "ws_42" });
  const clipboard = stubClipboardData();
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardCopy(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 1);
  assert.deepEqual(
    [...clipboard.written.keys()].sort(),
    [SCENE_CLIPBOARD_MIME, "text/html", "text/plain"].sort(),
  );
  const payload = JSON.parse(
    clipboard.written.get(SCENE_CLIPBOARD_MIME)!,
  ) as SceneClipboardPayloadV1;
  assert.deepEqual(payload.roots, ["group_proof"]);
  // Display/debug only — never trusted — but it must be what the session knows.
  assert.equal(payload.workspaceHint, "ws_42");
  assert.equal(clipboard.written.get("text/plain"), payload.readableText);
  assert.equal(reportError.mock.callCount(), 0);
});

it("copy over the 1 MiB cap still writes internal + plain, and says so", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  const stat = scene.nodes.text_proof_stat;
  assert.ok(stat.kind.kind === "text");
  stat.kind.content = "x".repeat(1_100_000);
  const { deps, reportError } = harness({ scene });
  const clipboard = stubClipboardData();
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardCopy(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 1);
  assert.ok(clipboard.written.has(SCENE_CLIPBOARD_MIME));
  assert.ok(clipboard.written.has("text/plain"));
  assert.equal(clipboard.written.has("text/html"), false);
  assert.deepEqual(reportError.mock.calls.map((call) => call.arguments[0]), [
    "This selection is over the 1 MiB clipboard limit — it will paste in this browser, but not into another app.",
  ]);
});

it("copy is a NON-EVENT with nothing selected — the browser keeps its own copy", () => {
  const { deps, reportError } = harness({ selectedNodeId: null });
  const clipboard = stubClipboardData();
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardCopy(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 0);
  assert.equal(clipboard.written.size, 0);
  assert.equal(reportError.mock.callCount(), 0);
});

/** The harvested ad plus a SECOND page carrying one node — the only way to
 * state "the selection is not on the page the session is showing". */
function sceneWithSecondPage(): Scene {
  const scene = clone(HARVESTED_AD_PAGE);
  const stray = structuredClone(scene.nodes.text_proof_stat);
  stray.id = "text_on_page_two";
  stray.children = [];
  scene.nodes[stray.id] = stray;
  scene.pages.page_two = {
    ...scene.pages[AD_PAGE_ID],
    children: [stray.id],
    id: "page_two",
    name: "Page two",
  };
  return scene;
}

it("copy ignores a selection that lives on ANOTHER page (R11)", () => {
  // Belt and braces: `serializeSubtree` refuses a cross-page root of its own
  // accord, so this pins the OUTER guard's answer (a non-event) rather than
  // introducing the refusal.
  const { deps } = harness({
    scene: sceneWithSecondPage(),
    selectedNodeId: "text_on_page_two",
  });
  const clipboard = stubClipboardData();
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardCopy(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 0);
  assert.equal(clipboard.written.size, 0);
});

it("copy leaves a focused field's own clipboard alone", () => {
  const { deps } = harness();
  const clipboard = stubClipboardData();
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardCopy(deps, event, {
    isContentEditable: false,
    tagName: "TEXTAREA",
  });

  assert.equal(event.prevented(), 0);
  assert.equal(clipboard.written.size, 0);
});

/** Run `body` with a stubbed `document.getSelection()`. Node has no `document`
 * at all, so this installs one and removes it again — the rule under test is
 * exactly "what does the DOM say the user has selected". */
function withDomSelection(
  selection: { isCollapsed: boolean } | null,
  body: () => void,
): void {
  const host = globalThis as { document?: unknown };
  const before = host.document;
  host.document = { getSelection: () => selection };
  try {
    body();
  } finally {
    if (before === undefined) {
      delete host.document;
    } else {
      host.document = before;
    }
  }
}

it("copy and cut YIELD to a live text selection in the shell", () => {
  // The canvas is CanvasKit — it hosts no DOM text — so a non-collapsed DOM
  // selection always belongs to the shell around it (a chat message, a label,
  // an artifact title). Copying the selected node instead would steal the
  // user's copy; cutting would additionally delete something they never aimed
  // at. Neither event is ours.
  const copyRun = harness();
  const copyClipboard = stubClipboardData();
  const copyEvent = clipboardEvent(copyClipboard.data);
  const cutRun = harness();
  const cutClipboard = stubClipboardData();
  const cutEvent = clipboardEvent(cutClipboard.data);

  withDomSelection({ isCollapsed: false }, () => {
    handleSceneClipboardCopy(copyRun.deps, copyEvent, CANVAS_TARGET);
    handleSceneClipboardCut(cutRun.deps, cutEvent, CANVAS_TARGET);
  });

  assert.equal(copyEvent.prevented(), 0);
  assert.equal(copyClipboard.written.size, 0);
  assert.equal(cutEvent.prevented(), 0);
  assert.equal(cutClipboard.written.size, 0);
  assert.equal(cutRun.applyEdit.mock.callCount(), 0);
  assert.equal(cutRun.canApply.mock.callCount(), 0);
  assert.equal(copyRun.reportError.mock.callCount(), 0);
  assert.equal(cutRun.reportError.mock.callCount(), 0);
});

it("a COLLAPSED selection — a caret, or none at all — is not a text selection", () => {
  const collapsed = harness();
  const collapsedClipboard = stubClipboardData();
  const collapsedEvent = clipboardEvent(collapsedClipboard.data);
  const absent = harness();
  const absentClipboard = stubClipboardData();
  const absentEvent = clipboardEvent(absentClipboard.data);

  withDomSelection({ isCollapsed: true }, () => {
    handleSceneClipboardCopy(collapsed.deps, collapsedEvent, CANVAS_TARGET);
  });
  withDomSelection(null, () => {
    handleSceneClipboardCopy(absent.deps, absentEvent, CANVAS_TARGET);
  });

  assert.equal(collapsedEvent.prevented(), 1);
  assert.ok(collapsedClipboard.written.has(SCENE_CLIPBOARD_MIME));
  assert.equal(absentEvent.prevented(), 1);
  assert.ok(absentClipboard.written.has(SCENE_CLIPBOARD_MIME));
});

// ── cut ────────────────────────────────────────────────────────────────────

it("cut copies THEN deletes the copied root — one structured edit", () => {
  const { applyEdit, deps } = harness();
  const clipboard = stubClipboardData();
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardCut(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 1);
  assert.ok(clipboard.written.has(SCENE_CLIPBOARD_MIME));
  assert.equal(applyEdit.mock.callCount(), 1);
  assert.deepEqual(
    applyEdit.mock.calls[0].arguments[0],
    deleteEdit({ kind: "node", id: "group_proof" }),
  );
});

it("cut with nothing selected copies nothing and deletes nothing", () => {
  const { applyEdit, deps } = harness({ selectedNodeId: null });
  const clipboard = stubClipboardData();
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardCut(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 0);
  assert.equal(clipboard.written.size, 0);
  assert.equal(applyEdit.mock.callCount(), 0);
});

it("cut refused by a read-only document: no copy, no delete, one message", () => {
  const { applyEdit, canApply, deps, reportError } = harness();
  canApply.mock.mockImplementation(() => false);
  const clipboard = stubClipboardData();
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardCut(deps, event, CANVAS_TARGET);

  assert.equal(clipboard.written.size, 0);
  assert.equal(applyEdit.mock.callCount(), 0);
  assert.deepEqual(reportError.mock.calls.map((call) => call.arguments[0]), [
    "This document isn't accepting edits right now.",
  ]);
});

// ── paste: the internal fast path ──────────────────────────────────────────

it("paste of an internal payload applies ONE batch — a single undo frame", () => {
  const { applyOps, deps, reportError } = harness();
  const clipboard = stubClipboardData({
    [SCENE_CLIPBOARD_MIME]: JSON.stringify(HEADLINE_PAYLOAD),
  });
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardPaste(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 1);
  assert.equal(applyOps.mock.callCount(), 1);
  const [operations, intent] = applyOps.mock.calls[0].arguments;
  assert.equal(intent, "clipboard.paste");
  // One insert per node in the payload's closure — the materializer's batch,
  // handed over whole.
  assert.equal(operations.length, HEADLINE_PAYLOAD.nodes.length);
  assert.equal(reportError.mock.callCount(), 0);
});

it("paste reads the html envelope when the internal mime did not survive", () => {
  const { applyOps, deps } = harness();
  const clipboard = stubClipboardData({
    "text/html": encodeClipboardHtml(HEADLINE_PAYLOAD)!,
    "text/plain": HEADLINE_PAYLOAD.readableText,
  });
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardPaste(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 1);
  assert.equal(applyOps.mock.callCount(), 1);
});

it("a copy round-trips through the same stub clipboard into a paste", () => {
  const { applyOps, deps } = harness({ selectedNodeId: "text_headline" });
  const clipboard = stubClipboardData();
  const copy = clipboardEvent(clipboard.data);
  handleSceneClipboardCopy(deps, copy, CANVAS_TARGET);

  // The SAME DataTransfer, read back — what the OS clipboard does between the
  // two events, minus the OS.
  const paste = clipboardEvent(clipboard.data);
  handleSceneClipboardPaste(deps, paste, CANVAS_TARGET);

  assert.equal(paste.prevented(), 1);
  assert.equal(applyOps.mock.callCount(), 1);
});

it(
  "the browser's own ClipboardEvent + DataTransfer round-trip",
  {
    skip:
      "jsdom implements neither ClipboardEvent nor DataTransfer (both are " +
      "`undefined` on a JSDOM window), so a real semantic clipboard event " +
      "cannot be constructed here. The stub round-trip above covers the " +
      "handler contract; the real-event path is Task 12's live walk.",
  },
  () => {},
);

it("cascade generations advance 1 → 2 on repeated paste, keyed per source", () => {
  const { applyOps, deps } = harness();
  const clipboard = stubClipboardData({
    [SCENE_CLIPBOARD_MIME]: JSON.stringify(HEADLINE_PAYLOAD),
  });

  handleSceneClipboardPaste(deps, clipboardEvent(clipboard.data), CANVAS_TARGET);
  handleSceneClipboardPaste(deps, clipboardEvent(clipboard.data), CANVAS_TARGET);

  assert.equal(applyOps.mock.callCount(), 2);
  const first = rootTransformOf(applyOps.mock.calls[0].arguments[0]);
  const second = rootTransformOf(applyOps.mock.calls[1].arguments[0]);
  assert.equal(second.x - first.x, 10);
  assert.equal(second.y - first.y, 10);

  // A DIFFERENT source root starts its own count at generation 1 — the same
  // step off ITS box, not the third step off the first one's.
  const other = stubClipboardData({
    [SCENE_CLIPBOARD_MIME]: JSON.stringify(GROUP_PAYLOAD),
  });
  handleSceneClipboardPaste(deps, clipboardEvent(other.data), CANVAS_TARGET);
  const third = rootTransformOf(applyOps.mock.calls[2].arguments[0]);
  assert.equal(third.x - GROUP_PAYLOAD.bounds.x, 10);
});

it("a refused batch does NOT advance the cascade — the next paste retries at 1", () => {
  const { applyOps, deps } = harness();
  applyOps.mock.mockImplementation(() => false);
  const clipboard = stubClipboardData({
    [SCENE_CLIPBOARD_MIME]: JSON.stringify(HEADLINE_PAYLOAD),
  });

  handleSceneClipboardPaste(deps, clipboardEvent(clipboard.data), CANVAS_TARGET);
  handleSceneClipboardPaste(deps, clipboardEvent(clipboard.data), CANVAS_TARGET);

  const first = rootTransformOf(applyOps.mock.calls[0].arguments[0]);
  const second = rootTransformOf(applyOps.mock.calls[1].arguments[0]);
  assert.deepEqual(second, first);
});

// ── W2: a cross-DOCUMENT image paste, and the server's tenancy gate ────────
//
// The live-walk defect: `scene.assets` is a PER-DOCUMENT map, so pasting an
// image copied from ANOTHER document of the SAME workspace found the id
// unregistered here and refused — wrong outcome and wrong sentence. The
// payload now carries the record, and whether this workspace may hold those
// bytes is the SERVER's question: the hook probes each foreign record before
// it applies anything (founder ruling 3).

/** The one-asset image payload, and a target document whose registry is empty
 * — the cross-document shape verbatim. */
const HERO_PAYLOAD = serializeSubtree(HARVESTED_AD_PAGE, AD_PAGE_ID, "image_hero")!;

function emptyAssetScene(): Scene {
  const scene = clone(HARVESTED_AD_PAGE);
  scene.assets = {};
  return scene;
}

/** Let every already-scheduled microtask AND macrotask run. The probe path is
 * async by ruling, so a case that asserts its outcome must wait for it — and a
 * case that asserts the SYNC path asserts before calling this. */
async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

function internalPasteEvent(payload: SceneClipboardPayloadV1) {
  return clipboardEvent(
    stubClipboardData({ [SCENE_CLIPBOARD_MIME]: JSON.stringify(payload) }).data,
  );
}

it("probes each foreign asset, then upserts it at the head of ONE batch (W2)", async () => {
  const probeAsset = mock.fn<(assetId: string) => Promise<boolean>>(async () => true);
  const { applyOps, deps } = harness({
    probeAsset,
    scene: emptyAssetScene(),
    selectedNodeId: null,
  });
  const event = internalPasteEvent(HERO_PAYLOAD);

  handleSceneClipboardPaste(deps, event, CANVAS_TARGET);

  // The event is ours before the await — `preventDefault` can never wait.
  assert.equal(event.prevented(), 1);
  assert.equal(applyOps.mock.callCount(), 0, "the write must wait for the probe");
  await flush();

  assert.deepEqual(
    probeAsset.mock.calls.map((call) => call.arguments[0]),
    ["asset_ing_2b0928ca4f3a3c70"],
  );
  assert.equal(applyOps.mock.callCount(), 1);
  const [operations, intent] = applyOps.mock.calls[0].arguments;
  assert.equal(intent, "clipboard.paste");
  assert.deepEqual(
    operations.map((operation) => (operation as { kind: string }).kind),
    ["upsert_asset", "insert_node"],
  );
  assert.deepEqual(
    (operations[0] as unknown as { asset: { id: string } }).asset,
    HERO_PAYLOAD.assets[0],
  );
});

it("a probe that says no refuses by count and applies NOTHING (W2)", async () => {
  const probeAsset = mock.fn<(assetId: string) => Promise<boolean>>(async () => false);
  const { applyOps, deps, reportError } = harness({
    probeAsset,
    scene: emptyAssetScene(),
    selectedNodeId: null,
  });

  handleSceneClipboardPaste(deps, internalPasteEvent(HERO_PAYLOAD), CANVAS_TARGET);
  await flush();

  assert.equal(applyOps.mock.callCount(), 0);
  assert.deepEqual(reportError.mock.calls.map((call) => call.arguments[0]), [
    "1 image in this clipboard belongs to another workspace",
  ]);
});

it("the refusal counts the FAILED probes, and pluralizes (W2)", async () => {
  // Two foreign records, both refused by the server's gate.
  const payload = structuredClone(HERO_PAYLOAD);
  const second = structuredClone(payload.assets[0]);
  second.id = "asset_ing_second";
  payload.assets.push(second);
  payload.assetIds.push(second.id);
  const probeAsset = mock.fn<(assetId: string) => Promise<boolean>>(async () => false);
  const { applyOps, deps, reportError } = harness({
    probeAsset,
    scene: emptyAssetScene(),
    selectedNodeId: null,
  });

  handleSceneClipboardPaste(deps, internalPasteEvent(payload), CANVAS_TARGET);
  await flush();

  assert.equal(probeAsset.mock.callCount(), 2);
  assert.equal(applyOps.mock.callCount(), 0);
  assert.deepEqual(reportError.mock.calls.map((call) => call.arguments[0]), [
    "2 images in this clipboard belong to another workspace",
  ]);
});

it("one refused probe among several refuses the WHOLE paste (W2)", async () => {
  const payload = structuredClone(HERO_PAYLOAD);
  const second = structuredClone(payload.assets[0]);
  second.id = "asset_ing_second";
  payload.assets.push(second);
  payload.assetIds.push(second.id);
  const probeAsset = mock.fn<(assetId: string) => Promise<boolean>>(
    async (assetId) => assetId !== "asset_ing_second",
  );
  const { applyOps, deps, reportError } = harness({
    probeAsset,
    scene: emptyAssetScene(),
    selectedNodeId: null,
  });

  handleSceneClipboardPaste(deps, internalPasteEvent(payload), CANVAS_TARGET);
  await flush();

  assert.equal(applyOps.mock.callCount(), 0);
  assert.deepEqual(reportError.mock.calls.map((call) => call.arguments[0]), [
    "1 image in this clipboard belongs to another workspace",
  ]);
});

it("a probe that REJECTS is a no — the gate fails closed (W2)", async () => {
  const probeAsset = mock.fn<(assetId: string) => Promise<boolean>>(async () => {
    throw new Error("network down");
  });
  const { applyOps, deps, reportError } = harness({
    probeAsset,
    scene: emptyAssetScene(),
    selectedNodeId: null,
  });

  handleSceneClipboardPaste(deps, internalPasteEvent(HERO_PAYLOAD), CANVAS_TARGET);
  await flush();

  assert.equal(applyOps.mock.callCount(), 0);
  assert.deepEqual(reportError.mock.calls.map((call) => call.arguments[0]), [
    "1 image in this clipboard belongs to another workspace",
  ]);
});

it("re-checks the write gate AFTER the probe — spend-first (W2)", async () => {
  // The Task-8 ingestion precedent: the lock can be turned on, or the engine
  // can go read-only, while the probe travels.
  const probeAsset = mock.fn<(assetId: string) => Promise<boolean>>(async () => true);
  const { applyOps, canApply, deps, reportError } = harness({
    probeAsset,
    scene: emptyAssetScene(),
    selectedNodeId: null,
  });
  handleSceneClipboardPaste(deps, internalPasteEvent(HERO_PAYLOAD), CANVAS_TARGET);
  canApply.mock.mockImplementation(() => false);
  await flush();

  assert.equal(applyOps.mock.callCount(), 0);
  assert.deepEqual(reportError.mock.calls.map((call) => call.arguments[0]), [
    "This document isn't accepting edits right now.",
  ]);
});

it("plans against the CURRENT scene, not the one the probe started on (W2)", async () => {
  // `deps` is the live latest-value object the hook re-writes each render, so
  // the document can gain the asset (or change outright) while the probe is in
  // flight. Re-reading it means the paste registers only what is STILL missing.
  const probeAsset = mock.fn<(assetId: string) => Promise<boolean>>(async () => true);
  const { applyOps, deps } = harness({
    probeAsset,
    scene: emptyAssetScene(),
    selectedNodeId: null,
  });

  handleSceneClipboardPaste(deps, internalPasteEvent(HERO_PAYLOAD), CANVAS_TARGET);
  deps.scene = HARVESTED_AD_PAGE;
  await flush();

  assert.equal(applyOps.mock.callCount(), 1);
  assert.deepEqual(
    applyOps.mock.calls[0].arguments[0].map(
      (operation) => (operation as { kind: string }).kind,
    ),
    ["insert_node"],
  );
});

it("never probes when the document already holds every record — and stays SYNC (W2)", () => {
  const probeAsset = mock.fn<(assetId: string) => Promise<boolean>>(async () => true);
  const { applyOps, deps } = harness({ probeAsset, selectedNodeId: null });

  handleSceneClipboardPaste(deps, internalPasteEvent(HERO_PAYLOAD), CANVAS_TARGET);

  // Asserted with NO await at all: a paste that needs no registration must
  // still reach the write path inside the event's own turn.
  assert.equal(applyOps.mock.callCount(), 1);
  assert.equal(probeAsset.mock.callCount(), 0);
});

it("an asset-free paste never probes either — and stays SYNC (W2)", () => {
  const probeAsset = mock.fn<(assetId: string) => Promise<boolean>>(async () => true);
  const { applyOps, deps } = harness({ probeAsset });

  handleSceneClipboardPaste(deps, internalPasteEvent(HEADLINE_PAYLOAD), CANVAS_TARGET);

  assert.equal(applyOps.mock.callCount(), 1);
  assert.equal(probeAsset.mock.callCount(), 0);
});

it("⌘D never probes — same document, every asset already present (W2)", () => {
  const probeAsset = mock.fn<(assetId: string) => Promise<boolean>>(async () => true);
  const { applyOps, deps } = harness({ probeAsset, selectedNodeId: "image_hero" });

  handleSceneClipboardDuplicate(deps, duplicateEvent(), CANVAS_TARGET);

  assert.equal(applyOps.mock.callCount(), 1);
  assert.equal(probeAsset.mock.callCount(), 0);
});

it("the DEFAULT probe asks the design BFF for the asset (W2)", async () => {
  const responses: Array<{ ok: boolean }> = [{ ok: true }];
  const fetchSpy = mock.fn<(input: string) => Promise<{ ok: boolean }>>(
    async () => responses.shift() ?? { ok: false },
  );
  const original = (globalThis as { fetch?: unknown }).fetch;
  (globalThis as { fetch?: unknown }).fetch = fetchSpy;
  try {
    // No `probeAsset` injected: this is the production default.
    const { applyOps, deps } = harness({
      scene: emptyAssetScene(),
      selectedNodeId: null,
    });
    handleSceneClipboardPaste(deps, internalPasteEvent(HERO_PAYLOAD), CANVAS_TARGET);
    await flush();

    assert.deepEqual(
      fetchSpy.mock.calls.map((call) => call.arguments[0]),
      [`${DESIGN_API_BFF_PREFIX}/assets/asset_ing_2b0928ca4f3a3c70`],
    );
    assert.equal(applyOps.mock.callCount(), 1);
  } finally {
    (globalThis as { fetch?: unknown }).fetch = original;
  }
});

it("R11: an off-page selection never drags the paste onto its page", () => {
  // WITHOUT the cross-page guard the planner would derive the parent from the
  // selection — `text_on_page_two`'s own parent — and this paste would land on
  // a page the user is not even looking at. The guard makes the selection
  // null, so the paste goes to the page the session IS showing.
  const { applyOps, deps } = harness({
    scene: sceneWithSecondPage(),
    selectedNodeId: "text_on_page_two",
  });
  const clipboard = stubClipboardData({
    [SCENE_CLIPBOARD_MIME]: JSON.stringify(HEADLINE_PAYLOAD),
  });

  handleSceneClipboardPaste(deps, clipboardEvent(clipboard.data), CANVAS_TARGET);

  assert.equal(applyOps.mock.callCount(), 1);
  const rootInsert = applyOps.mock.calls[0].arguments[0][0] as unknown as {
    parent: { id: string; kind: string };
  };
  assert.deepEqual(rootInsert.parent, { id: AD_PAGE_ID, kind: "page" });
});

it("paste refused by a read-only document: no ops, one message", () => {
  const { applyOps, canApply, deps, reportError } = harness();
  canApply.mock.mockImplementation(() => false);
  const clipboard = stubClipboardData({
    [SCENE_CLIPBOARD_MIME]: JSON.stringify(HEADLINE_PAYLOAD),
  });
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardPaste(deps, event, CANVAS_TARGET);

  assert.equal(applyOps.mock.callCount(), 0);
  assert.deepEqual(reportError.mock.calls.map((call) => call.arguments[0]), [
    "This document isn't accepting edits right now.",
  ]);
});

// ── paste: the external classes ────────────────────────────────────────────

it("R9: a files-bearing paste NEVER silently becomes a text paste", () => {
  const { applyOps, deps, reportError } = harness();
  const clipboard = stubClipboardData({ "text/plain": "a caption" }, [
    new File(["bytes"], "notes.pdf", { type: "application/pdf" }),
  ]);
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardPaste(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 1);
  assert.equal(applyOps.mock.callCount(), 0);
  assert.deepEqual(reportError.mock.calls.map((call) => call.arguments[0]), [
    "Only PNG, JPEG, WebP, and SVG images can be pasted.",
  ]);
});

it("R9: a clipboard carrying ONLY disallowed files refuses out loud, never in silence", () => {
  // The GIF hole. With no text, no html and no internal carrier, the
  // classifier's honest answer is `none` — but a human who pasted a picture
  // and heard nothing at all would read that as a broken editor. Files
  // present means the paste is ours to answer for, whatever the text classes
  // would have said.
  const { applyOps, deps, reportError } = harness();
  const clipboard = stubClipboardData({}, [
    new File(["bytes"], "loop.gif", { type: "image/gif" }),
  ]);
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardPaste(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 1);
  assert.equal(applyOps.mock.callCount(), 0);
  assert.deepEqual(reportError.mock.calls.map((call) => call.arguments[0]), [
    "Only PNG, JPEG, WebP, and SVG images can be pasted.",
  ]);
});

it("read-only OUTRANKS the allowlist refusal, and still claims the event", () => {
  // Both halves of the precedence ruling. The allowlist sentence would
  // mislead here — an allowed PNG would not have pasted either — so the
  // read-only sentence is the honest one. But the paste is still ours: we
  // spoke about the event, so the browser does not also get to.
  const { applyOps, canApply, deps, reportError } = harness();
  canApply.mock.mockImplementation(() => false);
  const clipboard = stubClipboardData({}, [
    new File(["bytes"], "loop.gif", { type: "image/gif" }),
  ]);
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardPaste(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 1);
  assert.equal(applyOps.mock.callCount(), 0);
  assert.deepEqual(reportError.mock.calls.map((call) => call.arguments[0]), [
    "This document isn't accepting edits right now.",
  ]);
});

it("image files reach the Task-8 seam with the rejected names beside them", () => {
  const onExternalImages = mock.fn<(files: File[], rejected: string[]) => void>();
  const { deps, reportError } = harness({ onExternalImages });
  const clipboard = stubClipboardData({}, [
    new File(["bytes"], "shot.png", { type: "image/png" }),
    new File(["bytes"], "notes.pdf", { type: "application/pdf" }),
  ]);
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardPaste(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 1);
  assert.equal(onExternalImages.mock.callCount(), 1);
  const [files, rejected] = onExternalImages.mock.calls[0].arguments;
  assert.deepEqual(
    files.map((file) => file.name),
    ["shot.png"],
  );
  assert.deepEqual(rejected, ["notes.pdf"]);
  assert.equal(reportError.mock.callCount(), 0);
});

it("image files refuse LOUDLY while Task 8 is unwired", () => {
  const { deps, reportError } = harness();
  const clipboard = stubClipboardData({}, [
    new File(["bytes"], "shot.png", { type: "image/png" }),
  ]);
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardPaste(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 1);
  assert.deepEqual(reportError.mock.calls.map((call) => call.arguments[0]), [
    "Pasting images isn't available yet.",
  ]);
});

it("svg markup routes to the Task-8 seam, and refuses the same way without it", () => {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg"><rect /></svg>';
  const onSvgMarkup = mock.fn<(svg: string) => void>();
  const wired = harness({ onSvgMarkup });
  const wiredEvent = clipboardEvent(stubClipboardData({ "text/plain": svg }).data);
  handleSceneClipboardPaste(wired.deps, wiredEvent, CANVAS_TARGET);
  assert.equal(wiredEvent.prevented(), 1);
  assert.deepEqual(onSvgMarkup.mock.calls[0].arguments, [svg]);

  const bare = harness();
  const bareEvent = clipboardEvent(stubClipboardData({ "text/plain": svg }).data);
  handleSceneClipboardPaste(bare.deps, bareEvent, CANVAS_TARGET);
  assert.equal(bareEvent.prevented(), 1);
  assert.deepEqual(bare.reportError.mock.calls.map((call) => call.arguments[0]), [
    "Pasting images isn't available yet.",
  ]);
});

// ── paste: plain text (Task 9) ─────────────────────────────────────────────
//
// R26 replaced the Task-7 seam: plain text is no longer left native and no
// longer routed to an `onPlainText` callback — it is handled INSIDE this file,
// so the two tests that pinned the seam are gone rather than adapted.
//
// The two shapes below are the whole feature: a selected text node has its
// CONTENT replaced (spans remapped by the shipped rich-text machinery, never a
// raw spread), and anything else mints a new text node at the viewport centre.

/** The pasted characters, verbatim: leading/trailing spaces and a newline that
 * must survive into the document untouched (R30 — no trimming anywhere). */
const PASTED_TEXT = "  Trusted by 400 clinics\nsince 2019  ";

/** The literal R28 fixes for a minted node, restated here so a silent change
 * to either constant fails a test rather than a design review. */
const PASTED_TEXT_WIDTH = 720; // round(0.6 × min(1200, 1200))
const PASTED_TEXT_BOUNDS_HEIGHT = 44; // ceil(2 lines × 16 × 1.35)

/** The R27 injection point. `spansVectorForContentEdit` is an ESM live binding,
 * so it cannot be replaced in the module under test — it rides on the deps
 * object instead, defaulting to the real import. The wrapper here DELEGATES to
 * that same real function, so the assertions are against real output and the
 * call arguments both. */
function recordingSpansVector() {
  return mock.fn(spansVectorForContentEdit);
}

function plainTextEvent(text = PASTED_TEXT) {
  return clipboardEvent(stubClipboardData({ "text/plain": text }).data);
}

/** The one batch a plain-text paste applied, with its intent. */
function appliedTextPaste(
  applyOps: ReturnType<typeof harness>["applyOps"],
): Operation[] {
  assert.equal(applyOps.mock.callCount(), 1);
  const [operations, intent] = applyOps.mock.calls[0].arguments;
  assert.equal(intent, "clipboard.paste-text");
  return operations;
}

/** The node an `insert_node` op carries. */
function insertedNode(operation: Operation): Node {
  return (operation as unknown as { node: Node }).node;
}

it("plain text over a selected text node REPLACES its content through updateTextNode", () => {
  const spansVector = recordingSpansVector();
  const { applyOps, deps, reportError } = harness({
    selectedNodeId: "text_headline",
    spansVectorForContentEdit: spansVector,
  });
  const event = plainTextEvent();

  handleSceneClipboardPaste(deps, event, CANVAS_TARGET);

  // R26: the paste is OURS now — claimed, and exactly one undo frame.
  assert.equal(event.prevented(), 1);
  const operations = appliedTextPaste(applyOps);
  assert.equal(operations.length, 1);

  // The op is the ENGINE's own builder, applied to the STORED node — built
  // here the same way, so a hand-rolled `update_node` shape cannot pass.
  const stored = HARVESTED_AD_PAGE.nodes["text_headline"];
  const spans = spansVectorForContentEdit(
    stored.kind as TextNode,
    PASTED_TEXT,
    [],
  );
  assert.deepEqual(
    operations[0],
    updateTextNode(stored, { content: PASTED_TEXT, spans }),
  );

  // The spans vector came FROM the rich-text machinery — never a raw spread.
  assert.equal(spansVector.mock.callCount(), 1);
  const [nodeArg, contentArg, nextSpansArg] = spansVector.mock.calls[0].arguments;
  assert.equal(nodeArg, stored.kind);
  assert.equal(contentArg, PASTED_TEXT);
  assert.deepEqual(nextSpansArg, []);
  assert.equal(reportError.mock.callCount(), 0);
});

it("a SPANNED node keeps the rich-text function's own remap of its spans", () => {
  // The case the plan named: a two-colour headline, fully replaced. What the
  // surviving spans are is `spansVectorForContentEdit`'s contract, not this
  // file's — so the assertion is equality with that function's own answer for
  // this exact input, which is the only way this stays true when the rich-text
  // rules change.
  const scene = clone(HARVESTED_AD_PAGE);
  const headline = scene.nodes["text_headline"];
  const storedSpans: TextSpan[] = [
    { start: 0, end: 5, font_weight: 800 },
    { start: 6, end: 11, italic: true },
  ];
  (headline.kind as TextNode).spans = storedSpans;
  const spansVector = recordingSpansVector();
  const { applyOps, deps } = harness({
    scene,
    selectedNodeId: "text_headline",
    spansVectorForContentEdit: spansVector,
  });

  handleSceneClipboardPaste(deps, plainTextEvent(), CANVAS_TARGET);

  const operations = appliedTextPaste(applyOps);
  const expected = spansVectorForContentEdit(
    headline.kind as TextNode,
    PASTED_TEXT,
    storedSpans,
  );
  assert.deepEqual(
    operations[0],
    updateTextNode(headline, { content: PASTED_TEXT, spans: expected }),
  );
  // The STORED spans are what was handed in as the next vector — the document's
  // own styling, re-anchored to the new content by that function.
  assert.deepEqual(spansVector.mock.calls[0].arguments[2], storedSpans);
});

it("plain text with NOTHING selected mints a text node at the viewport centre", () => {
  const viewportPageCenter = mock.fn(() => ({ x: 800, y: 500 }));
  const { applyOps, deps, reportError } = harness({
    selectedNodeId: null,
    viewportPageCenter,
  });
  const event = plainTextEvent();

  handleSceneClipboardPaste(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 1);
  const operations = appliedTextPaste(applyOps);
  assert.equal(operations.length, 1);
  const insert = operations[0] as unknown as {
    kind: string;
    parent: { id: string; kind: string };
  };
  assert.equal(insert.kind, "insert_node");
  assert.deepEqual(insert.parent, { id: AD_PAGE_ID, kind: "page" });

  const node = insertedNode(operations[0]);
  assert.equal(node.kind.kind, "text");
  // VERBATIM: the pasted characters, spaces and newline intact.
  assert.equal((node.kind as TextNode).content, PASTED_TEXT);
  assert.equal(node.name, "Pasted text");
  // Childless, and re-minted by the materializer — never the placeholder id.
  assert.deepEqual(node.children, []);
  assert.notEqual(node.id, "pasted-text");
  // Fixed width / hug height, the fixture's own precedent for a text node.
  assert.deepEqual(node.size, {
    width: { kind: "fixed", value: PASTED_TEXT_WIDTH },
    height: { kind: "hug" },
  });
  // A text node with empty fills paints nothing, so it is born with one.
  assert.equal(node.fills.length, 1);
  // Centred on the viewport point: the box's own left edge is half its width
  // to the left of the centre, and the page parent's origin is (0,0).
  assert.equal(node.transform.x, 800 - PASTED_TEXT_WIDTH / 2);
  assert.equal(node.transform.y, 500 - PASTED_TEXT_BOUNDS_HEIGHT / 2);
  assert.equal(node.computed, null);
  assert.equal(reportError.mock.callCount(), 0);
});

it("the PAGE's own centre is the fallback when there is no viewport to ask", () => {
  // Two ways the canvas can decline: the callback is absent (nothing wired it),
  // or it is there and answers null (the canvas is showing another document).
  // Both land the same place — the middle of the page.
  const absent = harness({ selectedNodeId: null });
  handleSceneClipboardPaste(absent.deps, plainTextEvent(), CANVAS_TARGET);
  const fromAbsent = insertedNode(appliedTextPaste(absent.applyOps)[0]);

  const nulled = harness({
    selectedNodeId: null,
    viewportPageCenter: () => null,
  });
  handleSceneClipboardPaste(nulled.deps, plainTextEvent(), CANVAS_TARGET);
  const fromNull = insertedNode(appliedTextPaste(nulled.applyOps)[0]);

  assert.equal(fromAbsent.transform.x, 600 - PASTED_TEXT_WIDTH / 2);
  assert.equal(fromAbsent.transform.y, 600 - PASTED_TEXT_BOUNDS_HEIGHT / 2);
  assert.deepEqual(fromNull.transform, fromAbsent.transform);
});

it("a selected IMAGE mints a text node — never a content write on a picture", () => {
  const { applyOps, deps } = harness({ selectedNodeId: "image_hero" });

  handleSceneClipboardPaste(deps, plainTextEvent(), CANVAS_TARGET);

  const operations = appliedTextPaste(applyOps);
  assert.ok(
    operations.every(
      (operation) => (operation as { kind: string }).kind !== "update_node",
    ),
  );
  assert.equal(insertedNode(operations[0]).kind.kind, "text");
});

it("a LOCKED text node is not a paste target — the text is minted instead", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  scene.nodes["text_headline"].locked = true;
  const { applyOps, deps } = harness({ scene, selectedNodeId: "text_headline" });

  handleSceneClipboardPaste(deps, plainTextEvent(), CANVAS_TARGET);

  const operations = appliedTextPaste(applyOps);
  const insert = operations[0] as unknown as { kind: string };
  assert.equal(insert.kind, "insert_node");
  assert.equal(insertedNode(operations[0]).kind.kind, "text");
});

it("an unlocked auto-layout selection takes the minted text INTO the row", () => {
  // Founder ruling 2 / the R2 ladder, unchanged: the placement planner decides
  // this, exactly as it does for an internal paste.
  const { applyOps, deps } = harness({ selectedNodeId: "auto_row_copy" });

  handleSceneClipboardPaste(deps, plainTextEvent(), CANVAS_TARGET);

  const operations = appliedTextPaste(applyOps);
  const insert = operations[0] as unknown as {
    index: number;
    parent: { id: string; kind: string };
  };
  assert.deepEqual(insert.parent, { id: "auto_row_copy", kind: "node" });
  assert.equal(
    insert.index,
    HARVESTED_AD_PAGE.nodes["auto_row_copy"].children.length,
  );
});

it("a read-only document refuses a plain-text paste, applying nothing", () => {
  const { applyOps, canApply, deps, reportError } = harness();
  canApply.mock.mockImplementation(() => false);
  const event = plainTextEvent();

  handleSceneClipboardPaste(deps, event, CANVAS_TARGET);

  assert.equal(applyOps.mock.callCount(), 0);
  // No files rode along, so the event is NOT claimed — the T7 precedence, read
  // only and unchanged by Task 9.
  assert.equal(event.prevented(), 0);
  assert.deepEqual(reportError.mock.calls.map((call) => call.arguments[0]), [
    "This document isn't accepting edits right now.",
  ]);
});

it("an empty clipboard is a complete non-event — not even a write-gate question", () => {
  const { applyOps, canApply, deps, reportError } = harness();
  const event = clipboardEvent(stubClipboardData().data);

  handleSceneClipboardPaste(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 0);
  assert.equal(applyOps.mock.callCount(), 0);
  assert.equal(reportError.mock.callCount(), 0);
  assert.equal(canApply.mock.callCount(), 0);
});

it("paste leaves a focused field's own paste alone", () => {
  const { applyOps, deps } = harness();
  const clipboard = stubClipboardData({
    [SCENE_CLIPBOARD_MIME]: JSON.stringify(HEADLINE_PAYLOAD),
  });
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardPaste(deps, event, {
    isContentEditable: true,
    tagName: "DIV",
  });

  assert.equal(event.prevented(), 0);
  assert.equal(applyOps.mock.callCount(), 0);
  assert.equal(clipboard.reads.length, 0);
});

// ── ⌘D ─────────────────────────────────────────────────────────────────────

it("⌘D duplicates the CURRENT SELECTION and touches no clipboard API at all", () => {
  const { applyOps, deps } = harness({ selectedNodeId: "text_headline" });
  // Ruling 4: the duplicate bypasses the OS clipboard entirely. The
  // synchronous half of that is structural — the handler is handed a keyboard
  // event, which carries no `DataTransfer` at all — so what is left to watch
  // is the ASYNC surface, `navigator.clipboard`, which any code path could
  // reach for. `navigator` is a getter-only global in Node, hence the
  // descriptor swap rather than an assignment.
  const clipboardApi = { read: mock.fn(), readText: mock.fn(), write: mock.fn(), writeText: mock.fn() };
  const before = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { clipboard: clipboardApi },
  });
  try {
    const event = duplicateEvent();
    handleSceneClipboardDuplicate(deps, event, CANVAS_TARGET);
    assert.equal(event.prevented(), 1);
  } finally {
    if (before) {
      Object.defineProperty(globalThis, "navigator", before);
    }
  }

  assert.equal(applyOps.mock.callCount(), 1);
  const [operations, intent] = applyOps.mock.calls[0].arguments;
  assert.equal(intent, "clipboard.duplicate");
  assert.equal(operations.length, HEADLINE_PAYLOAD.nodes.length);
  for (const call of Object.values(clipboardApi)) {
    assert.equal(call.mock.callCount(), 0);
  }
});

it("⌘D cascades: the second duplicate of the same node steps twice", () => {
  const { applyOps, deps } = harness({ selectedNodeId: "text_headline" });

  handleSceneClipboardDuplicate(deps, duplicateEvent(), CANVAS_TARGET);
  handleSceneClipboardDuplicate(deps, duplicateEvent(), CANVAS_TARGET);

  const first = rootTransformOf(applyOps.mock.calls[0].arguments[0]);
  const second = rootTransformOf(applyOps.mock.calls[1].arguments[0]);
  assert.equal(second.x - first.x, 10);
  assert.equal(second.y - first.y, 10);
});

it("⌘D preventDefaults even when the duplicate is refused — no browser bookmark", () => {
  const { applyOps, canApply, deps, reportError } = harness();
  canApply.mock.mockImplementation(() => false);
  const event = duplicateEvent();

  handleSceneClipboardDuplicate(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 1);
  assert.equal(applyOps.mock.callCount(), 0);
  assert.deepEqual(reportError.mock.calls.map((call) => call.arguments[0]), [
    "This document isn't accepting edits right now.",
  ]);
});

it("⌘D is not ⇧⌘D, ⌥⌘D, a bare D, or anything typed into a field", () => {
  const cases: Array<[
    Parameters<typeof duplicateEvent>[0],
    { isContentEditable: boolean; tagName: string } | null,
  ]> = [
    [{ shiftKey: true }, CANVAS_TARGET],
    [{ altKey: true }, CANVAS_TARGET],
    [{ metaKey: false }, CANVAS_TARGET],
    [{ key: "c" }, CANVAS_TARGET],
    [{}, { isContentEditable: false, tagName: "INPUT" }],
  ];
  for (const [overrides, target] of cases) {
    const { applyOps, deps } = harness();
    const event = duplicateEvent(overrides);
    handleSceneClipboardDuplicate(deps, event, target);
    assert.equal(event.prevented(), 0);
    assert.equal(applyOps.mock.callCount(), 0);
  }
});

it("⌘D with an unarmed session never preventDefaults", () => {
  const { applyOps, deps } = harness({ documentId: null });
  const event = duplicateEvent();

  handleSceneClipboardDuplicate(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 0);
  assert.equal(applyOps.mock.callCount(), 0);
});

it("⌘D with nothing selected is a non-event past the preventDefault", () => {
  const { applyOps, deps, reportError } = harness({ selectedNodeId: null });
  const event = duplicateEvent();

  handleSceneClipboardDuplicate(deps, event, CANVAS_TARGET);

  assert.equal(event.prevented(), 1);
  assert.equal(applyOps.mock.callCount(), 0);
  assert.equal(reportError.mock.callCount(), 0);
});

// ── Task 10: the outbound image/png representation (ruling 4, R31–R35) ─────

/**
 * What Task 10 adds to a copy, and the ONE thing it may never cost.
 *
 * A copied IMAGE node should paste into Preview or Slack as a picture, which
 * an OS clipboard only understands as `image/png` — and `image/png` can only
 * be written through the async `navigator.clipboard.write`, never through the
 * event's synchronous `setData`. So the copy path does BOTH: the shipped sync
 * trio first and unchanged (the internal payload is never at risk), then one
 * best-effort async write whose every failure is swallowed.
 *
 * The seams below (`writeClipboardItems`, `fetchAssetBytes`, `rasterToPng`)
 * ride the deps object with production defaults — jsdom hosts neither
 * `ClipboardItem` nor a canvas that can decode an image, so a test injects
 * fakes rather than asserting against a browser this runner does not have.
 */

/** The harvested ad with its one image asset re-typed, so a case can say
 * "this copy is of a png / a webp / an svg" without a second fixture. */
function sceneWithImageMime(
  mime: string | null,
  options: { digest?: boolean; vector?: boolean } = {},
): Scene {
  const scene = clone(HARVESTED_AD_PAGE);
  const record = scene.assets.asset_ing_2b0928ca4f3a3c70;
  record.media = { ...record.media, mime_type: mime };
  if (options.digest === false) {
    record.media = { ...record.media, digest: null };
  }
  if (options.vector) {
    record.vector = {
      has_transparency: true,
      height: 64,
      path_data: null,
      view_box: [0, 0, 64, 64],
      width: 64,
    };
    record.raster = null;
  }
  return scene;
}

/** A `writeClipboardItems` fake with the THREE outcomes a real browser has:
 * it resolves (the item was taken), it rejects (denied permission, no user
 * activation), or it THROWS SYNCHRONOUSLY — which is not hypothetical, since
 * the production writer constructs `ClipboardItem`s in its own synchronous
 * prefix and that constructor throws a TypeError in engines that refuse
 * promise-valued entries (Firefox). All three are R31 swallows. */
function clipboardWriterFake(
  order: string[],
  outcome: "resolve" | "reject" | "throw" = "resolve",
) {
  const batches: Array<Record<string, Blob | Promise<Blob>>> = [];
  const write = mock.fn((items: Array<Record<string, Blob | Promise<Blob>>>) => {
    order.push("clipboard.write");
    batches.push(...items);
    if (outcome === "throw") {
      throw new TypeError("ClipboardItem does not accept a promise value");
    }
    return outcome === "reject"
      ? Promise.reject(new Error("clipboard write denied"))
      : Promise.resolve();
  });
  return { batches, write };
}

/** Everything the async step is allowed to touch, defaulted so a case states
 * only what it is about. */
function imageCopyDeps(
  scene: Scene,
  overrides: {
    bytes?: (url: string) => Promise<Blob>;
    order?: string[];
    outcome?: "resolve" | "reject" | "throw";
    raster?: (source: Blob, mime: string) => Promise<Blob>;
  } = {},
) {
  const order = overrides.order ?? [];
  const writer = clipboardWriterFake(order, overrides.outcome ?? "resolve");
  const fetched: string[] = [];
  const rasterCalls: Array<{ mime: string; size: number }> = [];
  const fetchAssetBytes = mock.fn(async (url: string) => {
    fetched.push(url);
    return overrides.bytes
      ? await overrides.bytes(url)
      : new Blob([new Uint8Array([1, 2, 3])], { type: "image/png" });
  });
  const rasterToPng = mock.fn(async (source: Blob, mime: string) => {
    rasterCalls.push({ mime, size: source.size });
    return overrides.raster
      ? await overrides.raster(source, mime)
      : new Blob([new Uint8Array([9, 9])], { type: "image/png" });
  });
  const { applyEdit, deps, reportError } = harness({
    fetchAssetBytes,
    rasterToPng,
    scene,
    selectedNodeId: "image_hero",
    writeClipboardItems: writer.write,
  });
  return { applyEdit, deps, fetched, order, rasterCalls, reportError, writer };
}

/** One turn of the microtask + macrotask queues — long enough for the async
 * step's own `.catch` to have run, so "nothing surfaced" is a real claim. */
async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

it("copying a png IMAGE node writes html + plain + png to the async clipboard", async () => {
  const { deps, fetched, rasterCalls, reportError, writer } = imageCopyDeps(
    sceneWithImageMime("image/png"),
  );
  const clipboard = stubClipboardData();
  const event = clipboardEvent(clipboard.data);

  handleSceneClipboardCopy(deps, event, CANVAS_TARGET);
  await settle();

  assert.equal(writer.write.mock.callCount(), 1);
  assert.equal(writer.batches.length, 1);
  const item = writer.batches[0];
  assert.deepEqual(Object.keys(item).sort(), [
    "image/png",
    "text/html",
    "text/plain",
  ]);
  // The SAME strings the sync path wrote — one copy, two carriers.
  assert.equal(
    await (item["text/html"] as Blob).text(),
    clipboard.written.get("text/html"),
  );
  assert.equal(
    await (item["text/plain"] as Blob).text(),
    clipboard.written.get("text/plain"),
  );
  const png = await (item["image/png"] as Promise<Blob>);
  assert.equal(png.type, "image/png");
  // The bytes came through the scene's own passthrough resolver — never a
  // hand-built asset URL.
  assert.deepEqual(fetched, [
    "/api/clue/design-public/asset-store/2b0928ca4f3a3c70c5c2fed22996f0428da219c953a14e71567b73c1d8af937a",
  ]);
  // R35(b): a png asset's bytes ARE the representation — nothing to rasterize.
  assert.deepEqual(rasterCalls, []);
  assert.equal(reportError.mock.callCount(), 0);
});

it("jpeg, webp and svg assets route through the raster seam; png does not", async () => {
  for (const mime of ["image/jpeg", "image/webp", "image/svg+xml"]) {
    const { deps, rasterCalls, writer } = imageCopyDeps(sceneWithImageMime(mime));
    const event = clipboardEvent(stubClipboardData().data);

    handleSceneClipboardCopy(deps, event, CANVAS_TARGET);
    await (writer.batches[0]["image/png"] as Promise<Blob>);

    assert.deepEqual(
      rasterCalls.map((call) => call.mime),
      [mime],
    );
  }
  // A record with no mime at all and a `vector` payload IS an svg — the
  // fallback R33 states, not a guess about the bytes.
  const vector = imageCopyDeps(sceneWithImageMime(null, { vector: true }));
  handleSceneClipboardCopy(
    vector.deps,
    clipboardEvent(stubClipboardData().data),
    CANVAS_TARGET,
  );
  await (vector.writer.batches[0]["image/png"] as Promise<Blob>);
  assert.deepEqual(
    vector.rasterCalls.map((call) => call.mime),
    ["image/svg+xml"],
  );
});

it("the sync setData trio runs BEFORE the async write, and a rejection is swallowed", async () => {
  const order: string[] = [];
  const { deps, reportError, writer } = imageCopyDeps(
    sceneWithImageMime("image/png"),
    { order, outcome: "reject" },
  );
  const clipboard = stubClipboardData({}, [], order);
  const event = clipboardEvent(clipboard.data);

  // No throw out of the handler, and no message: the copy ALREADY succeeded.
  handleSceneClipboardCopy(deps, event, CANVAS_TARGET);
  await settle();

  assert.deepEqual(order, [
    `setData:${SCENE_CLIPBOARD_MIME}`,
    "setData:text/plain",
    "setData:text/html",
    "clipboard.write",
  ]);
  assert.equal(writer.write.mock.callCount(), 1);
  // The internal payload is intact — a png failure never costs the copy.
  assert.equal(
    JSON.parse(clipboard.written.get(SCENE_CLIPBOARD_MIME)!).roots[0],
    "image_hero",
  );
  assert.equal(reportError.mock.callCount(), 0);
});

it("a cut of an image node keeps the same order — writeCopy is the one path", async () => {
  const order: string[] = [];
  const { deps, writer } = imageCopyDeps(sceneWithImageMime("image/png"), {
    order,
  });
  const clipboard = stubClipboardData({}, [], order);

  handleSceneClipboardCut(deps, clipboardEvent(clipboard.data), CANVAS_TARGET);
  await settle();

  assert.deepEqual(order.at(-1), "clipboard.write");
  assert.equal(writer.write.mock.callCount(), 1);
});

it("NON-image roots never reach the async writer (founder ruling 4's scope)", async () => {
  for (const rootId of ["group_proof", "text_headline", "auto_row_copy"]) {
    const { deps, writer } = imageCopyDeps(sceneWithImageMime("image/png"));
    const clipboard = stubClipboardData();
    handleSceneClipboardCopy(
      { ...deps, selectedNodeId: rootId },
      clipboardEvent(clipboard.data),
      CANVAS_TARGET,
    );
    await settle();
    assert.equal(writer.write.mock.callCount(), 0, rootId);
    // Not vacuous: each of these IS a real copy — it simply carries no
    // picture. (`group_proof` is a group over an ellipse and a text node,
    // `auto_row_copy` the auto-layout row over the headline and that group.)
    assert.equal(clipboard.written.size, 3, rootId);
  }
});

it("an over-cap image copy writes no clipboard item — the envelope is the item", async () => {
  const scene = sceneWithImageMime("image/png");
  scene.nodes.image_hero.name = "x".repeat(1_100_000);
  const { deps, reportError, writer } = imageCopyDeps(scene);
  const clipboard = stubClipboardData();

  handleSceneClipboardCopy(deps, clipboardEvent(clipboard.data), CANVAS_TARGET);
  await settle();

  assert.equal(writer.write.mock.callCount(), 0);
  // The baseline is untouched by the skip: internal + plain still landed, and
  // the reduced-copy sentence is the shipped one.
  assert.ok(clipboard.written.has(SCENE_CLIPBOARD_MIME));
  assert.ok(clipboard.written.has("text/plain"));
  assert.equal(clipboard.written.has("text/html"), false);
  assert.equal(reportError.mock.callCount(), 1);
});

it("with no async writer available the copy is exactly the shipped sync one", async () => {
  const { deps } = imageCopyDeps(sceneWithImageMime("image/png"));
  const clipboard = stubClipboardData();

  handleSceneClipboardCopy(
    { ...deps, writeClipboardItems: undefined },
    clipboardEvent(clipboard.data),
    CANVAS_TARGET,
  );
  await settle();

  assert.deepEqual(
    [...clipboard.written.keys()].sort(),
    [SCENE_CLIPBOARD_MIME, "text/html", "text/plain"].sort(),
  );
});

it("a missing digest or a non-ok fetch rejects the png promise and nothing else", async () => {
  const noDigest = imageCopyDeps(
    sceneWithImageMime("image/png", { digest: false }),
  );
  handleSceneClipboardCopy(
    noDigest.deps,
    clipboardEvent(stubClipboardData().data),
    CANVAS_TARGET,
  );
  await assert.rejects(
    noDigest.writer.batches[0]["image/png"] as Promise<Blob>,
  );
  // Never fetched: there was no honest URL to fetch.
  assert.deepEqual(noDigest.fetched, []);
  await settle();
  assert.equal(noDigest.reportError.mock.callCount(), 0);

  const failing = imageCopyDeps(sceneWithImageMime("image/png"), {
    bytes: () => Promise.reject(new Error("404")),
  });
  handleSceneClipboardCopy(
    failing.deps,
    clipboardEvent(stubClipboardData().data),
    CANVAS_TARGET,
  );
  await assert.rejects(failing.writer.batches[0]["image/png"] as Promise<Blob>);
  await settle();
  assert.equal(failing.reportError.mock.callCount(), 0);
});

it("a writer that THROWS SYNCHRONOUSLY never escapes the copy handler", async () => {
  // The real path this pins: `new ClipboardItem({...})` is constructed inside
  // the writer's own synchronous prefix, and it throws a TypeError in engines
  // that do not accept promise-valued entries. An exception escaping a window
  // `copy` listener is exactly the broken-editor shape this file forbids —
  // R31's swallow covers a throw, not only a rejection.
  const { deps, reportError, writer } = imageCopyDeps(
    sceneWithImageMime("image/png"),
    { outcome: "throw" },
  );
  const clipboard = stubClipboardData();

  assert.doesNotThrow(() => {
    handleSceneClipboardCopy(deps, clipboardEvent(clipboard.data), CANVAS_TARGET);
  });
  await settle();

  assert.equal(writer.write.mock.callCount(), 1);
  // The baseline stands, whole: the enrichment failed before it began.
  assert.deepEqual(
    [...clipboard.written.keys()].sort(),
    [SCENE_CLIPBOARD_MIME, "text/html", "text/plain"].sort(),
  );
  assert.equal(reportError.mock.callCount(), 0);
});

it("a throwing writer still lets a CUT delete — the copy half cannot abort it", async () => {
  // Worse than a lost picture: an exception out of `writeCopy` would return
  // before `applyEdit(deleteEdit(...))`, so a cut on such a browser would copy
  // the node and never remove it.
  const { applyEdit, deps, writer } = imageCopyDeps(
    sceneWithImageMime("image/png"),
    { outcome: "throw" },
  );
  const clipboard = stubClipboardData();

  assert.doesNotThrow(() => {
    handleSceneClipboardCut(deps, clipboardEvent(clipboard.data), CANVAS_TARGET);
  });
  await settle();

  assert.equal(writer.write.mock.callCount(), 1);
  assert.equal(applyEdit.mock.callCount(), 1);
  assert.deepEqual(
    applyEdit.mock.calls[0].arguments[0],
    deleteEdit({ id: "image_hero", kind: "node" }),
  );
  assert.ok(clipboard.written.has(SCENE_CLIPBOARD_MIME));
});

// ── Task 11: the open text session keeps its own clipboard (R37d) ──────────
//
// The rich-text caret session's overlay IS a `<textarea>`
// (`components/scene-artifact-canvas.tsx`), so while it is open every clipboard
// event is aimed at a typing target and `ownedSession` returns null for all
// three handlers. That is the whole guard — there is no session-aware branch
// anywhere in this file, and there must not be one: a paste inside the session
// is an ordinary `beforeinput` the span algebra already handles
// (`adapter/scene-text-session.test.ts`, R37a–c).

const SESSION_TEXTAREA_TARGET = { isContentEditable: false, tagName: "TEXTAREA" };

it("copy, cut and paste aimed at the session's TEXTAREA do nothing at all", () => {
  const seeds: Record<string, string>[] = [
    { [SCENE_CLIPBOARD_MIME]: JSON.stringify(GROUP_PAYLOAD) },
    { "text/plain": PASTED_TEXT },
  ];
  for (const seed of seeds) {
    for (const handler of [
      handleSceneClipboardCopy,
      handleSceneClipboardCut,
      handleSceneClipboardPaste,
    ]) {
      const { applyEdit, applyOps, deps, reportError } = harness();
      const clipboard = stubClipboardData(seed);
      const event = clipboardEvent(clipboard.data);

      handler(deps, event, SESSION_TEXTAREA_TARGET);

      // Not claimed, nothing written to the clipboard, nothing written to the
      // document, and not a word said about it.
      assert.equal(event.prevented(), 0);
      assert.equal(clipboard.written.size, 0);
      assert.equal(applyOps.mock.callCount(), 0);
      assert.equal(applyEdit.mock.callCount(), 0);
      assert.equal(reportError.mock.callCount(), 0);
    }
  }
});

it("…and the very same events DO act when the canvas is the target", () => {
  // The control for the guard above: without it every one of those events was
  // live, so the zero-counts are the TARGET's doing and not a dead fixture.
  const copy = harness();
  const copied = stubClipboardData();
  handleSceneClipboardCopy(copy.deps, clipboardEvent(copied.data), CANVAS_TARGET);
  assert.equal(copied.written.size, 3);

  const cut = harness();
  handleSceneClipboardCut(
    cut.deps,
    clipboardEvent(stubClipboardData().data),
    CANVAS_TARGET,
  );
  assert.equal(cut.applyEdit.mock.callCount(), 1);

  const internal = harness();
  const internalEvent = clipboardEvent(
    stubClipboardData({
      [SCENE_CLIPBOARD_MIME]: JSON.stringify(GROUP_PAYLOAD),
    }).data,
  );
  handleSceneClipboardPaste(internal.deps, internalEvent, CANVAS_TARGET);
  assert.equal(internalEvent.prevented(), 1);
  assert.equal(internal.applyOps.mock.callCount(), 1);

  const plain = harness({ selectedNodeId: "text_headline" });
  const plainEvent = clipboardEvent(
    stubClipboardData({ "text/plain": PASTED_TEXT }).data,
  );
  handleSceneClipboardPaste(plain.deps, plainEvent, CANVAS_TARGET);
  assert.equal(plainEvent.prevented(), 1);
  assert.equal(plain.applyOps.mock.callCount(), 1);
});
