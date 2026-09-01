import type {
  AssetId,
  Node,
  NodeId,
  PageId,
  Rect,
  Scene,
} from "../engine/scene/contracts";
import {
  nodePageSpaceBox,
  pageIdForNode,
  parentComputedOrigin,
} from "../engine/scene/sceneQueries";

/**
 * Scene clipboard Task 1 — the versioned DTO and the subtree serializer.
 *
 * The payload is a DTO, not the live store: `Node` is already a serializable
 * contract type, so the DTO reuses it verbatim, but every node is deep-cloned
 * at capture — a clipboard payload is a snapshot, and a later edit to the
 * scene must not reach into it. The envelope carries `kind` + `version` so a
 * future contract drift becomes a migration, not a crash.
 *
 * Everything here is pure: no clipboard API, no DOM, no transport. The event
 * wiring (Task 7) composes these functions; nothing composes them the other
 * way around.
 */

export const SCENE_CLIPBOARD_KIND = "clue.scene/clipboard";
export const SCENE_CLIPBOARD_MIME = "application/vnd.clue.scene+json";

export interface SceneClipboardPayloadV1 {
  kind: typeof SCENE_CLIPBOARD_KIND;
  version: 1;
  /** Display/debug only — NEVER trusted for auth. Asset resolution against
   * the pasting workspace's own store is the actual cross-workspace gate.
   * Born null here (a Scene names no workspace); the copy gesture may stamp
   * one before the payload reaches the OS clipboard. */
  workspaceHint: string | null;
  /** V1: exactly one root (the shipped selection model is single-node). */
  roots: NodeId[];
  /** Root + full descendant closure, DFS preorder — document order, parents
   * before children, which is exactly the insert order paste needs. */
  nodes: Node[];
  /** Workspace-scoped refs for every ImageNode in `nodes`, deduplicated. */
  assetIds: AssetId[];
  /** The root's page-space box — what placement planning offsets from. */
  bounds: { x: number; y: number; width: number; height: number };
  /** Pre-extracted text-node contents for the `text/plain` representation
   * (human-readable, never the JSON — the Excalidraw Safari-leak lesson). */
  readableText: string;
}

/**
 * Serialize `rootId`'s subtree from the scene's flat node map into a clipboard
 * payload. Returns null when the root resolves to no node — including a root
 * that lives on a different page than the one named, which would otherwise
 * serialize bounds against a page it is not on.
 */
export function serializeSubtree(
  scene: Scene,
  pageId: PageId,
  rootId: NodeId,
): SceneClipboardPayloadV1 | null {
  const root = scene.nodes[rootId];
  if (!root || pageIdForNode(scene, rootId) !== pageId) {
    return null;
  }

  // Closure via an iterative stack over `children`, emitting DFS preorder —
  // the same walk `flattenPageNodeIds` does, so payload order IS document
  // order. Children are pushed reversed so they pop first-child-first.
  const nodes: Node[] = [];
  const stack: NodeId[] = [rootId];
  while (stack.length > 0) {
    const id = stack.pop()!;
    const node = scene.nodes[id];
    if (!node) {
      // A dangling child id is a scene-invariant violation, not the copier's
      // to repair — the closure simply has nothing to capture for it.
      continue;
    }
    nodes.push(structuredClone(node));
    for (let index = node.children.length - 1; index >= 0; index -= 1) {
      stack.push(node.children[index]);
    }
  }

  const assetIds: AssetId[] = [];
  const seenAssets = new Set<AssetId>();
  for (const node of nodes) {
    if (node.kind.kind === "image" && !seenAssets.has(node.kind.asset_id)) {
      seenAssets.add(node.kind.asset_id);
      assetIds.push(node.kind.asset_id);
    }
  }

  return {
    kind: SCENE_CLIPBOARD_KIND,
    version: 1,
    workspaceHint: null,
    roots: [rootId],
    nodes,
    assetIds,
    bounds: rootPageSpaceBounds(scene, root),
    readableText: extractReadableText(nodes),
  };
}

/** Text-node contents in the order given (callers pass document order),
 * newline-joined — the payload's human-readable `text/plain` face. */
export function extractReadableText(nodes: readonly Node[]): string {
  const lines: string[] = [];
  for (const node of nodes) {
    if (node.kind.kind === "text") {
      lines.push(node.kind.content);
    }
  }
  return lines.join("\n");
}

/**
 * The root's page-space box. The engine's solved geometry (`absolute_box` /
 * `computed.layout_bounds`, via `nodePageSpaceBox`) is authoritative when it
 * exists; a node that has never been solved falls back to its parent-relative
 * transform rebased through `parentComputedOrigin` — (0,0) for page-parented
 * nodes, so the transform IS the page-space position there. Non-fixed
 * dimensions (hug/fill) have no honest unsolved size and read as 0.
 */
function rootPageSpaceBounds(scene: Scene, node: Node): Rect {
  const solved = nodePageSpaceBox(scene, node.id);
  if (solved) {
    return solved;
  }
  const origin = parentComputedOrigin(scene, node.id);
  return {
    x: origin.x + node.transform.x,
    y: origin.y + node.transform.y,
    width: node.size.width.kind === "fixed" ? node.size.width.value : 0,
    height: node.size.height.kind === "fixed" ? node.size.height.value : 0,
  };
}

// ── Task 2: envelope codec ─────────────────────────────────────────────────

/**
 * Cap on the payload's JSON, measured in UTF-8 BYTES. A scene subtree is
 * structure, not pixels — image nodes carry asset ids, never asset bytes —
 * so anything past 1 MiB is a bug, not a big design. Encode refuses rather
 * than truncates; the copy gesture still writes `text/plain`.
 */
export const CLIPBOARD_ENVELOPE_MAX_BYTES = 1_048_576;

/** The attribute that marks our carrier element inside `text/html` clipboard
 * data — the Figma-style envelope that survives OS clipboards and cross-tab
 * paste. Base64 payload, so the value is attribute-quote-safe by charset. */
const ENVELOPE_ATTRIBUTE = "data-clue-scene";

/**
 * Wrap a payload for the `text/html` clipboard representation, or null when
 * its JSON exceeds {@link CLIPBOARD_ENVELOPE_MAX_BYTES}.
 */
export function encodeClipboardHtml(payload: SceneClipboardPayloadV1): string | null {
  const json = JSON.stringify(payload);
  if (new TextEncoder().encode(json).byteLength > CLIPBOARD_ENVELOPE_MAX_BYTES) {
    return null;
  }
  return `<span ${ENVELOPE_ATTRIBUTE}="${utf8ToBase64(json)}"></span>`;
}

/**
 * Read a payload back out of pasted `text/html`, or null for anything that is
 * not (or no longer) a well-formed Clue scene envelope.
 *
 * Parse-only, by construction: the html goes through `DOMParser`, whose
 * documents are inert (scripts never execute, event handlers never fire), and
 * the ONLY thing read is the envelope attribute — no element is ever adopted
 * into the live document, and nothing here touches `innerHTML`. The decoded
 * JSON is then untrusted input like any other: it must clear
 * {@link validateClipboardPayload} before it becomes model objects.
 */
export function decodeClipboardHtml(html: string): SceneClipboardPayloadV1 | null {
  if (typeof DOMParser === "undefined") {
    return null;
  }
  const document = new DOMParser().parseFromString(html, "text/html");
  const encoded = document.querySelector(`[${ENVELOPE_ATTRIBUTE}]`)?.getAttribute(ENVELOPE_ATTRIBUTE);
  if (!encoded) {
    return null;
  }
  const json = base64ToUtf8(encoded);
  if (json === null) {
    return null;
  }
  let value: unknown;
  try {
    value = JSON.parse(json);
  } catch {
    return null;
  }
  return validateClipboardPayload(value);
}

const PAYLOAD_KEYS = [
  "kind",
  "version",
  "workspaceHint",
  "roots",
  "nodes",
  "assetIds",
  "bounds",
  "readableText",
] as const;

/**
 * Strict structural validation of an untrusted decoded value. Refusals, not
 * repairs: an unknown or missing top-level key, a wrong kind/version, a
 * malformed field, or a node graph that is not self-contained (roots or
 * children referencing nodes the payload does not carry, duplicate ids) all
 * return null — pasting a repaired guess would be fabrication.
 *
 * Depth is deliberate: top-level shape and the per-node invariants the paste
 * pipeline actually leans on (id / children / kind / transform / size / name).
 * Unknown keys INSIDE a node are allowed — optional contract fields come and
 * go within v1; the version field is what guards real contract drift.
 */
export function validateClipboardPayload(value: unknown): SceneClipboardPayloadV1 | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record);
  if (keys.length !== PAYLOAD_KEYS.length) {
    return null;
  }
  for (const key of PAYLOAD_KEYS) {
    if (!(key in record)) {
      return null;
    }
  }
  if (record.kind !== SCENE_CLIPBOARD_KIND || record.version !== 1) {
    return null;
  }
  if (record.workspaceHint !== null && typeof record.workspaceHint !== "string") {
    return null;
  }
  if (typeof record.readableText !== "string") {
    return null;
  }
  const roots = record.roots;
  // V1 carries exactly one root — the shipped selection model is single-node,
  // and the paste pipeline places exactly one subtree.
  if (!Array.isArray(roots) || roots.length !== 1 || typeof roots[0] !== "string") {
    return null;
  }
  const assetIds = record.assetIds;
  if (!Array.isArray(assetIds) || !assetIds.every((id) => typeof id === "string")) {
    return null;
  }
  if (!isValidBounds(record.bounds)) {
    return null;
  }
  const nodes = record.nodes;
  if (!Array.isArray(nodes) || nodes.length === 0) {
    return null;
  }
  const ids = new Set<string>();
  for (const node of nodes) {
    if (!isMinimalNode(node) || ids.has(node.id)) {
      return null;
    }
    ids.add(node.id);
  }
  for (const node of nodes as Array<{ children: string[] }>) {
    for (const child of node.children) {
      if (!ids.has(child)) {
        return null;
      }
    }
  }
  if (!ids.has(roots[0])) {
    return null;
  }
  return record as unknown as SceneClipboardPayloadV1;
}

function isValidBounds(value: unknown): value is Rect {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const record = value as Record<string, unknown>;
  if (Object.keys(record).length !== 4) {
    return false;
  }
  return (["x", "y", "width", "height"] as const).every(
    (key) => typeof record[key] === "number" && Number.isFinite(record[key]),
  );
}

/** The per-node invariants the paste pipeline leans on; extra keys allowed. */
function isMinimalNode(value: unknown): value is Node {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const record = value as Record<string, unknown>;
  if (typeof record.id !== "string" || record.id.length === 0) {
    return false;
  }
  if (record.name !== null && typeof record.name !== "string") {
    return false;
  }
  if (!Array.isArray(record.children) || !record.children.every((id) => typeof id === "string")) {
    return false;
  }
  const kind = record.kind;
  if (typeof kind !== "object" || kind === null || typeof (kind as { kind?: unknown }).kind !== "string") {
    return false;
  }
  const transform = record.transform;
  if (
    typeof transform !== "object" ||
    transform === null ||
    typeof (transform as { x?: unknown }).x !== "number" ||
    typeof (transform as { y?: unknown }).y !== "number"
  ) {
    return false;
  }
  return typeof record.size === "object" && record.size !== null;
}

// Base64 over UTF-8, both directions, browser- and Node-safe: btoa/atob are
// latin1-only, so the text goes through TextEncoder/TextDecoder and the
// binary string is built in chunks (a 1 MiB single spread would blow the
// argument limit). The decoder is `fatal`, so mangled bytes refuse instead of
// silently becoming U+FFFD.

function utf8ToBase64(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  const CHUNK = 0x8000;
  for (let index = 0; index < bytes.length; index += CHUNK) {
    binary += String.fromCharCode(...Array.from(bytes.subarray(index, index + CHUNK)));
  }
  return btoa(binary);
}

function base64ToUtf8(encoded: string): string | null {
  try {
    const binary = atob(encoded);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return null;
  }
}
