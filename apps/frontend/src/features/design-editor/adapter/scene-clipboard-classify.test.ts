import assert from "node:assert/strict";
import { it } from "node:test";
import { JSDOM } from "jsdom";
import { AD_PAGE_ID, HARVESTED_AD_PAGE } from "./__fixtures__/scene-nodes";
import {
  SCENE_CLIPBOARD_MIME,
  encodeClipboardHtml,
  serializeSubtree,
} from "./scene-clipboard";
import type { ClipboardSnapshot, PasteIntent } from "./scene-clipboard-classify";
import {
  ALLOWED_IMAGE_MIMES,
  classifyPaste,
  snapshotClipboardData,
} from "./scene-clipboard-classify";

/**
 * Clipboard Task 6 — the paste classifier: a synchronous DataTransfer snapshot
 * and a pure fall-through decision about what a paste IS.
 *
 * Two properties every case below exists to hold:
 *   the snapshot is SYNCHRONOUS and TOTAL — a DataTransfer is dead after any
 *   async boundary (the Firefox lesson), and `getData` throws on unknown types
 *   in some browsers, so every read defaults instead of propagating;
 *   the classifier FALLS THROUGH — a carrier that is present but unreadable
 *   (mangled internal JSON, html with no envelope, a file list with nothing
 *   allowed) never dead-ends the paste, it hands the decision to the next
 *   class down.
 *
 * The envelope class reaches the browser's DOMParser through
 * `decodeClipboardHtml`; node:test has no DOM, so the suite installs jsdom's —
 * the same inert, non-executing parser contract as the browser's.
 */
const DOM = new JSDOM("");
(globalThis as { DOMParser?: unknown }).DOMParser = DOM.window.DOMParser;

/** Two real payloads over the harvested ad, with DIFFERENT roots — so a case
 * that puts one in each carrier can prove WHICH carrier won, not merely that
 * something internal won. */
const GROUP_PAYLOAD = serializeSubtree(HARVESTED_AD_PAGE, AD_PAGE_ID, "group_proof")!;
const HEADLINE_PAYLOAD = serializeSubtree(HARVESTED_AD_PAGE, AD_PAGE_ID, "text_headline")!;
const GROUP_HTML = encodeClipboardHtml(GROUP_PAYLOAD)!;
const HEADLINE_HTML = encodeClipboardHtml(HEADLINE_PAYLOAD)!;

function snapshot(parts: Partial<ClipboardSnapshot> = {}): ClipboardSnapshot {
  return { internal: "", html: "", text: "", files: [], ...parts };
}

function imageFile(name: string, type: string): File {
  return new File(["bytes"], name, { type });
}

/** node:assert's `equal` does not narrow a discriminated union, so cases that
 * go on to read an intent's payload go through this — the `expectOps` /
 * `expectRefusal` precedent in the Task-5 suite, generalized over the kind. */
function expectKind<K extends PasteIntent["kind"]>(
  intent: PasteIntent,
  kind: K,
): Extract<PasteIntent, { kind: K }> {
  if (intent.kind !== kind) {
    assert.fail(`expected a ${kind} paste, got ${intent.kind}`);
  }
  return intent as Extract<PasteIntent, { kind: K }>;
}

// ── snapshotClipboardData ──────────────────────────────────────────────────

/** A DataTransfer-shaped stand-in: the three reads the snapshot makes, plus a
 * file list. `throwOn` reproduces the browsers that throw on an unknown type
 * rather than returning "". */
function fakeDataTransfer(options: {
  data?: Record<string, string>;
  files?: File[];
  throwOn?: string[];
}): { dt: DataTransfer; requested: string[] } {
  const requested: string[] = [];
  const data = options.data ?? {};
  const dt = {
    getData(type: string): string {
      requested.push(type);
      if (options.throwOn?.includes(type)) {
        throw new Error(`unsupported type: ${type}`);
      }
      return data[type] ?? "";
    },
    files: options.files ?? [],
  };
  return { dt: dt as unknown as DataTransfer, requested };
}

it("snapshots the three clipboard representations by their exact types", () => {
  const { dt, requested } = fakeDataTransfer({
    data: {
      [SCENE_CLIPBOARD_MIME]: JSON.stringify(GROUP_PAYLOAD),
      "text/html": GROUP_HTML,
      "text/plain": "proof stat",
    },
  });
  const snap = snapshotClipboardData(dt);
  assert.deepEqual(requested, [SCENE_CLIPBOARD_MIME, "text/html", "text/plain"]);
  assert.equal(snap.internal, JSON.stringify(GROUP_PAYLOAD));
  assert.equal(snap.html, GROUP_HTML);
  assert.equal(snap.text, "proof stat");
});

it("is synchronous — it returns a snapshot, never a promise", () => {
  // The whole reason this function exists: the DataTransfer is dead after any
  // async boundary, so nothing in the snapshot path may await.
  const { dt } = fakeDataTransfer({ data: { "text/plain": "hi" } });
  const snap = snapshotClipboardData(dt);
  assert.equal(typeof (snap as { then?: unknown }).then, "undefined");
  assert.equal(snap.text, "hi");
});

it("defaults every representation that throws to the empty string", () => {
  const { dt } = fakeDataTransfer({
    data: { "text/plain": "still readable" },
    throwOn: [SCENE_CLIPBOARD_MIME, "text/html"],
  });
  const snap = snapshotClipboardData(dt);
  assert.equal(snap.internal, "");
  assert.equal(snap.html, "");
  assert.equal(snap.text, "still readable");
});

it("copies the file list into a real array — never the live FileList", () => {
  const png = imageFile("b.png", "image/png");
  const live = [png];
  const { dt } = fakeDataTransfer({ files: live });
  const snap = snapshotClipboardData(dt);
  assert.ok(Array.isArray(snap.files));
  assert.notEqual(snap.files, live as unknown as File[]);
  assert.deepEqual(snap.files, [png]);
  // The browser's FileList empties when the event ends; the copy must not.
  live.length = 0;
  assert.equal(snap.files.length, 1);
});

// ── classifyPaste: priority ────────────────────────────────────────────────

it("prefers the internal mime over every other carrier", () => {
  const intent = classifyPaste(
    snapshot({
      internal: JSON.stringify(GROUP_PAYLOAD),
      html: HEADLINE_HTML,
      files: [imageFile("b.png", "image/png")],
      text: "<svg></svg>",
    }),
  );
  const pasted = expectKind(intent, "internal");
  // The GROUP payload, not the headline one that rode in the html envelope.
  assert.deepEqual(pasted.payload.roots, ["group_proof"]);
});

it("falls through to the html envelope when the internal mime is not JSON", () => {
  const intent = classifyPaste(
    snapshot({ internal: "{not json", html: HEADLINE_HTML, text: "headline" }),
  );
  const pasted = expectKind(intent, "internal");
  assert.deepEqual(pasted.payload.roots, ["text_headline"]);
});

it("falls through to the html envelope when the internal mime fails validation", () => {
  // Well-formed JSON, wrong shape — a decode failure must never dead-end the
  // paste, it hands down to the next carrier.
  const intent = classifyPaste(
    snapshot({
      internal: JSON.stringify({ kind: "clue.scene/clipboard", version: 99 }),
      html: HEADLINE_HTML,
      text: "headline",
    }),
  );
  const pasted = expectKind(intent, "internal");
  assert.deepEqual(pasted.payload.roots, ["text_headline"]);
});

it("reports the same intent kind for both internal carriers — the carrier is invisible downstream", () => {
  const viaMime = classifyPaste(snapshot({ internal: JSON.stringify(GROUP_PAYLOAD) }));
  const viaHtml = classifyPaste(snapshot({ html: GROUP_HTML }));
  assert.equal(viaMime.kind, "internal");
  assert.equal(viaHtml.kind, "internal");
  assert.deepEqual(viaMime, viaHtml);
});

it("prefers the html envelope over image files", () => {
  // The Chrome/Safari copy shape this pins: a subtree copy whose internal mime
  // was lost by the OS clipboard still arrives as html, and a screenshot-y png
  // may ride alongside it. The envelope is the higher-fidelity carrier, so it
  // wins — move the file block above the envelope block and this case reddens.
  const intent = classifyPaste(
    snapshot({ html: HEADLINE_HTML, files: [imageFile("b.png", "image/png")] }),
  );
  const pasted = expectKind(intent, "internal");
  assert.deepEqual(pasted.payload.roots, ["text_headline"]);
});

it("falls through to files when the html carries no envelope", () => {
  const png = imageFile("b.png", "image/png");
  const intent = classifyPaste(
    snapshot({
      internal: "",
      html: "<p>copied from a web page</p>",
      files: [png],
      text: "copied from a web page",
    }),
  );
  const pasted = expectKind(intent, "image-files");
  assert.deepEqual(pasted.files, [png]);
  assert.deepEqual(pasted.rejected, []);
});

it("prefers image files over svg markup in the text representation", () => {
  const png = imageFile("b.png", "image/png");
  const intent = classifyPaste(
    snapshot({ files: [png], text: "<svg viewBox='0 0 1 1'></svg>" }),
  );
  const pasted = expectKind(intent, "image-files");
  assert.deepEqual(pasted.files, [png]);
});

// ── classifyPaste: the file allowlist ──────────────────────────────────────

it("keeps only allowlisted files and names the ones it dropped", () => {
  const gif = imageFile("a.gif", "image/gif");
  const png = imageFile("b.png", "image/png");
  const intent = classifyPaste(snapshot({ files: [gif, png] }));
  const pasted = expectKind(intent, "image-files");
  assert.deepEqual(pasted.files, [png]);
  // Task 7 refuses LOUDLY by name — a silently dropped file is the failure.
  assert.deepEqual(pasted.rejected, ["a.gif"]);
});

it("accepts every allowlisted mime, and image/jpg as jpeg", () => {
  const files = [
    imageFile("a.png", "image/png"),
    imageFile("b.jpeg", "image/jpeg"),
    imageFile("c.webp", "image/webp"),
    imageFile("d.svg", "image/svg+xml"),
    // Some platforms stamp this non-standard spelling on a JPEG.
    imageFile("e.jpg", "image/jpg"),
  ];
  const intent = classifyPaste(snapshot({ files }));
  const pasted = expectKind(intent, "image-files");
  assert.deepEqual(
    pasted.files.map((file) => file.name),
    ["a.png", "b.jpeg", "c.webp", "d.svg", "e.jpg"],
  );
  assert.deepEqual(pasted.rejected, []);
});

it("falls through to the text classes when NOTHING in the file list is allowed", () => {
  const intent = classifyPaste(
    snapshot({ files: [imageFile("a.gif", "image/gif")], text: "hello" }),
  );
  const pasted = expectKind(intent, "plain-text");
  assert.equal(pasted.text, "hello");
});

it("exports the allowlist as the ruled four mimes", () => {
  assert.deepEqual(ALLOWED_IMAGE_MIMES, [
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/svg+xml",
  ]);
});

// ── classifyPaste: svg markup ──────────────────────────────────────────────

it("classifies bare svg markup", () => {
  const intent = classifyPaste(snapshot({ text: "<svg width='10'></svg>" }));
  const pasted = expectKind(intent, "svg-markup");
  assert.equal(pasted.svg, "<svg width='10'></svg>");
});

it("classifies svg markup behind an XML prolog — and keeps the prolog", () => {
  const text = '<?xml version="1.0" encoding="UTF-8"?>\n<svg></svg>';
  const intent = classifyPaste(snapshot({ text }));
  const pasted = expectKind(intent, "svg-markup");
  // The prolog is part of the document; only leading BOM/whitespace is cut.
  assert.equal(pasted.svg, text);
});

it("classifies BOM-prefixed svg markup, trimming the BOM and leading whitespace", () => {
  const intent = classifyPaste(snapshot({ text: "﻿\n  <svg></svg>\n" }));
  const pasted = expectKind(intent, "svg-markup");
  // Leading only — trailing bytes are the document's, not noise to trim.
  assert.equal(pasted.svg, "<svg></svg>\n");
});

it("classifies a BOM + prolog + whitespace lead-in as svg markup", () => {
  const intent = classifyPaste(
    snapshot({ text: '﻿  <?xml version="1.0"?> <svg></svg>' }),
  );
  const pasted = expectKind(intent, "svg-markup");
  assert.equal(pasted.svg, '<?xml version="1.0"?> <svg></svg>');
});

it("matches the svg tag case-insensitively", () => {
  const intent = classifyPaste(snapshot({ text: "<SVG></SVG>" }));
  expectKind(intent, "svg-markup");
});

it("does not treat text that merely CONTAINS svg markup as svg", () => {
  const intent = classifyPaste(snapshot({ text: "look at this <svg></svg>" }));
  const pasted = expectKind(intent, "plain-text");
  assert.equal(pasted.text, "look at this <svg></svg>");
});

it("treats a lone XML prolog as plain text", () => {
  const intent = classifyPaste(snapshot({ text: '<?xml version="1.0"?>' }));
  expectKind(intent, "plain-text");
});

// ── classifyPaste: plain text and the empty clipboard ──────────────────────

it("passes plain text through verbatim — surrounding whitespace included", () => {
  const intent = classifyPaste(snapshot({ text: "  Series B closed  " }));
  const pasted = expectKind(intent, "plain-text");
  assert.equal(pasted.text, "  Series B closed  ");
});

it("classifies whitespace-only text as nothing to paste", () => {
  assert.deepEqual(classifyPaste(snapshot({ text: "   \n\t  " })), { kind: "none" });
  // A lone BOM is whitespace too — there is no content behind it.
  assert.deepEqual(classifyPaste(snapshot({ text: "﻿" })), { kind: "none" });
});

it("classifies an entirely empty snapshot as nothing to paste", () => {
  assert.deepEqual(classifyPaste(snapshot()), { kind: "none" });
});

it("classifies a clipboard whose every carrier is unreadable as nothing to paste", () => {
  // Mangled internal JSON, envelope-free html, a disallowed file, blank text:
  // every class falls through, and the bottom of the chain is honest emptiness.
  assert.deepEqual(
    classifyPaste(
      snapshot({
        internal: "{",
        html: "<p>hi</p>",
        files: [imageFile("a.gif", "image/gif")],
        text: "  ",
      }),
    ),
    { kind: "none" },
  );
});

it("reads the snapshot, never mutating it", () => {
  const snap = snapshot({
    internal: "{bad",
    html: "<p>hi</p>",
    files: [imageFile("a.gif", "image/gif"), imageFile("b.png", "image/png")],
    text: "  <svg></svg>  ",
  });
  const before = structuredClone({ ...snap, files: snap.files.map((file) => file.name) });
  classifyPaste(snap);
  assert.deepEqual(
    { ...snap, files: snap.files.map((file) => file.name) },
    before,
  );
});
