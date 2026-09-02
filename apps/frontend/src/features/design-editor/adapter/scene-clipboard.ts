import type {
  AssetId,
  AssetRecord,
  Node,
  NodeId,
  Operation,
  PageId,
  ParentRef,
  Rect,
  Scene,
} from "../engine/scene/contracts";
import { insertNode } from "../engine/scene/operations";
import {
  nodePageSpaceBox,
  pageIdForNode,
  parentComputedOrigin,
} from "../engine/scene/sceneQueries";
import type { PastePlacement } from "./scene-clipboard-placement";

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
  /** W2: the RECORD behind every id in {@link assetIds}, copied verbatim from
   * the source document's registry.
   *
   * `scene.assets` is a PER-DOCUMENT map while assets themselves are
   * workspace-scoped, so a same-workspace paste into ANOTHER document finds
   * the id unregistered there — the live walk's defect. Carrying the records
   * lets the paste register what it references (`upsert_asset`) instead of
   * refusing a picture the workspace genuinely owns. It is NOT an auth claim:
   * the server's own tenancy gate is what proves the pasting workspace may
   * have these bytes (see `use-scene-clipboard.ts`'s probe). */
  assets: AssetRecord[];
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

  // The records behind those ids, cloned like the nodes — a payload is a
  // snapshot, so a later edit to the live registry must not reach into it. An
  // id the source document does not describe contributes nothing: a missing
  // record is a scene-invariant violation, not the copier's to invent, and the
  // validator refuses such a payload loudly at the paste boundary rather than
  // letting it paste a picture nothing can resolve.
  const assets: AssetRecord[] = [];
  for (const id of assetIds) {
    const record = scene.assets?.[id];
    if (record) {
      assets.push(structuredClone(record));
    }
  }

  return {
    kind: SCENE_CLIPBOARD_KIND,
    version: 1,
    workspaceHint: null,
    roots: [rootId],
    nodes,
    assetIds,
    assets,
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
  "assets",
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
  const assets = record.assets;
  if (!Array.isArray(assets)) {
    return null;
  }
  const describedAssets = new Set<string>();
  for (const asset of assets) {
    if (typeof asset !== "object" || asset === null || Array.isArray(asset)) {
      return null;
    }
    const id = (asset as { id?: unknown }).id;
    if (typeof id !== "string" || id.length === 0) {
      return null;
    }
    describedAssets.add(id);
  }
  // A payload that NAMES an asset it cannot describe is malformed: the target
  // document has nothing to register, so the picture could only paste as a
  // blank box. Refuse the payload rather than paste half of it.
  if (!assetIds.every((id) => describedAssets.has(id))) {
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

// ── Task 3: subtree re-mint ────────────────────────────────────────────────

/**
 * Give a validated payload's subtree a fresh identity inside the target
 * scene: every node gets a new `node-XXXXXXXX` id (the `mintGroupId`
 * precedent generalized — wrapped `crypto.randomUUID`, collision-retried
 * against BOTH the scene's `existingIds` and the ids minted earlier in this
 * batch), every `children` array is rewritten through the old→new map, and
 * the ROOT's name is suffixed `_2`-style against `siblingNames` until free
 * (descendants keep their names — they collide with nothing at their level).
 *
 * W1 — A NULL NAME INHERITS THE SOURCE ID. The layer tree labels a node
 * `node.name ?? `${kind} ${id}`` (`sceneQueries.ts::nodeDisplayName`), and
 * agent-authored nodes carry `name: null` with a readable id ("headline",
 * "main"). Keeping the null through a re-mint therefore renamed the copy to
 * "text node-a345153a" — the fresh id is machine identity, never a label a
 * human chose. So a null-named copy takes the SOURCE NODE'S ID as its name:
 * the identity the user already sees in the tree, carried over rather than
 * invented. `siblingNames` is a set of DISPLAY identities for the same reason
 * (`materializeClipboardPayload` builds it from `name ?? id`).
 *
 * The payload is read, never mutated: paste twice and the second paste
 * re-mints from the same untouched payload.
 */
export function remintSubtree(
  payload: SceneClipboardPayloadV1,
  existingIds: ReadonlySet<string>,
  siblingNames: ReadonlySet<string>,
): { nodes: Node[]; rootId: NodeId } {
  const minted = new Set<string>();
  const idMap = new Map<NodeId, NodeId>();
  for (const node of payload.nodes) {
    const fresh = mintNodeId((candidate) => existingIds.has(candidate) || minted.has(candidate));
    minted.add(fresh);
    idMap.set(node.id, fresh);
  }
  const nodes = payload.nodes.map((node, index) => {
    const copy = structuredClone(node);
    copy.id = idMap.get(node.id)!;
    // Validation guarantees the graph is self-contained, so every child
    // resolves; the fallback keeps a hand-built payload's dangling ref from
    // silently becoming an id the scene might actually contain.
    copy.children = node.children.map((child) => idMap.get(child) ?? child);
    // W1: the label the user already reads for this node — its name, or, for
    // an agent-authored node, its readable source id.
    const displayName = node.name ?? node.id;
    copy.name = index === 0 ? collisionFreeName(displayName, siblingNames) : displayName;
    return copy;
  });
  return { nodes, rootId: nodes[0].id };
}

/** A fresh node id nothing in `taken` already claims. Exported for Task 8's
 * external-image ingestion, which mints ids for nodes that were never in a
 * clipboard payload — ONE minter, so the two paths cannot drift. */
export function mintNodeId(taken: (candidate: string) => boolean): NodeId {
  let candidate = `node-${crypto.randomUUID().slice(0, 8)}`;
  while (taken(candidate)) {
    candidate = `node-${crypto.randomUUID().slice(0, 8)}`;
  }
  return candidate;
}

/** `headline` → `headline_2`, `_3`, … against the siblings' DISPLAY
 * identities. The base is opaque — no suffix parsing. */
function collisionFreeName(
  name: string,
  siblingNames: ReadonlySet<string>,
): string {
  if (!siblingNames.has(name)) {
    return name;
  }
  let counter = 2;
  while (siblingNames.has(`${name}_${counter}`)) {
    counter += 1;
  }
  return `${name}_${counter}`;
}

// ── Task 5: materialization ────────────────────────────────────────────────

/** Either a batch the caller can apply whole, or a reason it cannot — never
 * both, and never a partial batch. */
export type ClipboardMaterialization =
  | { ops: Operation[]; rootId: NodeId }
  | { refusal: string };

const EMPTY_CLIPBOARD_REFUSAL = "This clipboard is empty — there is nothing to paste";
const MALFORMED_CLIPBOARD_REFUSAL =
  "This clipboard is malformed — there is nothing safe to paste";

/**
 * Turn a validated payload plus a {@link PastePlacement} into ONE parents-first
 * `insert_node` batch of CHILDLESS nodes against `scene`, or refuse. The tree
 * is expressed by each op's parent ref and index, never by a populated
 * `children` array — see the batch-building comment below for why.
 *
 * Every refusal is decided before the first op is built, so a refusal enqueues
 * nothing — atomicity by construction rather than by rollback.
 *
 * W2 — ASSETS ARE CARRIED, NOT DEMANDED. `scene.assets` is a PER-DOCUMENT
 * registry, so gating on it refused a picture the SAME workspace owns merely
 * because this document had never seen it. The payload now carries each
 * referenced record, and a record missing from `knownAssetIds` is REGISTERED
 * by an `upsert_asset` at the head of the batch instead. The count-naming
 * refusal survives for the one case nothing can repair — an `assetIds` entry
 * with no record at all (which `validateClipboardPayload` already refuses, so
 * this is defence in depth). Whether the pasting workspace may hold those
 * bytes is the SERVER's tenancy gate to answer, not a client-side map lookup;
 * the hook probes it before it ever reaches here.
 *
 * The scene and the payload are read, never written: `remintSubtree` clones,
 * and only its output is edited. Paste twice from the same payload and the
 * second paste re-mints from the same untouched bytes.
 */
export function materializeClipboardPayload(
  scene: Scene,
  payload: SceneClipboardPayloadV1,
  placement: PastePlacement,
  knownAssetIds: ReadonlySet<string>,
): ClipboardMaterialization {
  if (payload.nodes.length === 0 || payload.roots.length !== 1) {
    return { refusal: EMPTY_CLIPBOARD_REFUSAL };
  }
  // W2: a record the payload carries is registered here (`upsert_asset`
  // below), so only an id the payload can neither describe NOR find already
  // registered is genuinely out of reach — another workspace's asset.
  const describedAssets = new Set(payload.assets.map((record) => record.id));
  const missing = payload.assetIds.filter(
    (id) => !knownAssetIds.has(id) && !describedAssets.has(id),
  ).length;
  if (missing > 0) {
    return {
      refusal:
        `${missing} image${missing === 1 ? "" : "s"} in this clipboard ` +
        `${missing === 1 ? "belongs" : "belong"} to another workspace`,
    };
  }

  // Names collide per PARENT, not per scene: the sibling set is exactly the
  // placement parent's existing children — as DISPLAY identities (W1: a
  // null-named sibling shows its id, and a pasted copy that inherited that
  // same id must still be suffixed clear of it).
  const parentChildren = childIdsOf(scene, placement.parent);
  const siblingNames = new Set<string>();
  for (const childId of parentChildren) {
    const sibling = scene.nodes[childId];
    if (sibling) {
      siblingNames.add(sibling.name ?? sibling.id);
    }
  }
  const { nodes, rootId } = remintSubtree(
    payload,
    new Set(Object.keys(scene.nodes)),
    siblingNames,
  );

  // Ruling R7: freehand overrides POSITION only. Rotation, skew and flips are
  // what the copied content LOOKS like; a paste moves it, it does not restyle
  // it. The delta this produces is also what R8 shifts stale boxes by.
  const rootBefore = nodes[0].transform;
  const delta =
    placement.kind === "freehand"
      ? { x: placement.transform.x - rootBefore.x, y: placement.transform.y - rootBefore.y }
      : null;
  if (placement.kind === "freehand") {
    nodes[0].transform = {
      ...rootBefore,
      x: placement.transform.x,
      y: placement.transform.y,
    };
  }

  for (const node of nodes) {
    // Ruling R8: `computed` is solved geometry from the OLD scene — derived
    // state that would be a lie here until the engine re-solves.
    node.computed = null;
    // A pinned node's `absolute_box` is authoritative geometry, so it travels
    // with the paste delta. Into-layout pastes leave it alone: the solver
    // re-places managed children, and shifting would be a guess with a
    // different answer.
    if (delta && node.absolute_box) {
      node.absolute_box = {
        ...node.absolute_box,
        x: node.absolute_box.x + delta.x,
        y: node.absolute_box.y + delta.y,
      };
    }
  }

  // Where each descendant sits: under the re-minted parent that names it, at
  // its position in that parent's children array.
  const seats = new Map<NodeId, { parent: ParentRef; index: number }>();
  let claimedTwice = false;
  for (const node of nodes) {
    node.children.forEach((childId, index) => {
      if (seats.has(childId)) {
        claimedTwice = true;
      }
      seats.set(childId, { parent: { kind: "node", id: node.id }, index });
    });
  }
  // `validateClipboardPayload` proves the graph is self-contained; it does not
  // prove it is ONE tree. An orphan, a second claim on a child, or a root
  // claimed as somebody's child leaves the seat lookup below with no honest
  // answer — refuse rather than invent a parent.
  if (
    claimedTwice ||
    seats.has(rootId) ||
    nodes.some((node, index) => index > 0 && !seats.has(node.id))
  ) {
    return { refusal: MALFORMED_CLIPBOARD_REFUSAL };
  }

  // The re-minted array is DFS preorder, so emitting in order IS parents-first.
  //
  // Every node is inserted CHILDLESS. lumen-core's `insert_node` refuses a node
  // whose children name nodes not yet in the scene (`op.child_missing`), and a
  // batch applies to a draft clone — so one such op would discard the entire
  // paste. The engine's own subtree-clone path does the same thing
  // (`clone.children.clear()`), and the reconcile insert path states the
  // invariant outright: insert top-down with an empty child list and let each
  // child's own InsertNode seat it under its parent. Preorder keeps every seat
  // index in bounds, so the tree that results is identical.
  const rootIndex =
    placement.kind === "into-layout" ? placement.index : parentChildren.length;
  const inserts = nodes.map((node, index) => {
    const childless = { ...node, children: [] };
    if (index === 0) {
      return insertNode(placement.parent, rootIndex, childless);
    }
    const seat = seats.get(node.id)!;
    return insertNode(seat.parent, seat.index, childless);
  });

  // REGISTER, THEN INSERT — the canonical pair (`use-scene-image-paste.ts`'s
  // Task-8 ingestion, `assetLibrary.ts::buildNodePlacementOperations`, and the
  // shipped Replace-image / Generate paths all lead with the record). A node
  // whose `asset_id` names a record this document does not hold resolves to no
  // bytes at all and fails the engine's strict asset validation, so the order
  // is load-bearing. Both halves ride the ONE batch the caller applies, so a
  // cross-document paste is still exactly one undo frame. A record the
  // document already holds is left alone — re-upserting it would be a write
  // the paste never needed.
  const upserts: Operation[] = payload.assets
    .filter((record) => !knownAssetIds.has(record.id))
    .map((record) => ({ kind: "upsert_asset", asset: structuredClone(record) }));
  return { ops: [...upserts, ...inserts], rootId };
}

/** The children a parent already holds — the page's or the node's. A parent
 * the scene does not know holds nothing, so an append lands at index 0. */
function childIdsOf(scene: Scene, parent: ParentRef): readonly NodeId[] {
  const container =
    parent.kind === "page" ? scene.pages[parent.id] : scene.nodes[parent.id];
  return container?.children ?? [];
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

// ── Task 10: outbound png for image-node copies ────────────────────────────

/**
 * The side an SVG with no declared size is rasterized at — the image cache's
 * own fallback (`imageCache.ts::DEFAULT_SVG_SIDE`), restated rather than
 * imported so this export path never reaches into the CanvasKit layer.
 */
const EXPORT_SVG_FALLBACK_SIDE = 512;

/**
 * Asset bytes → an `image/png` blob, for the ONE representation an OS
 * clipboard understands as a picture (ruling 4 / R32).
 *
 * Three routes, and no fourth answer:
 *   `image/png` — the bytes ARE the representation; resolved as-is, without
 *   so much as looking for a DOM.
 *   raster (`image/jpeg`, `image/webp`, anything else the browser can decode)
 *   — `createImageBitmap` where it exists, else an `<img>`, then a 2D canvas
 *   at the decoded size and `toBlob("image/png")`.
 *   `image/svg+xml` — the image cache's Image-element route verbatim (object
 *   URL → `<img>` → natural size, {@link EXPORT_SVG_FALLBACK_SIDE} when the
 *   markup declares none). Deliberately NOT `createImageBitmap(svgBlob)`,
 *   which is unsupported or flaky across engines while `<img src="x.svg">` is
 *   how every browser already draws one.
 *
 * REJECTS, NEVER PLACEHOLDERS. No DOM, a decode that fails, a missing 2D
 * context, a `toBlob` that yields null — each throws. The copy path treats
 * that as "this copy carries no picture", which is honest; a grey rectangle
 * on the user's clipboard would not be.
 */
export async function rasterToPngBlob(source: Blob, mime: string): Promise<Blob> {
  if (mime === "image/png") {
    return source;
  }
  if (typeof document === "undefined") {
    throw new Error("png export needs a DOM to rasterize with");
  }
  const decoded =
    mime === "image/svg+xml"
      ? await decodeSvgForExport(source)
      : await decodeRasterForExport(source);
  try {
    return await drawToPngBlob(decoded.image, decoded.width, decoded.height);
  } finally {
    decoded.release();
  }
}

/** A decoded image plus the size to draw it at, and the one call that frees
 * whatever the decode allocated (an object URL, a bitmap). */
interface DecodedExportImage {
  height: number;
  image: CanvasImageSource;
  release: () => void;
  width: number;
}

async function decodeSvgForExport(source: Blob): Promise<DecodedExportImage> {
  const url = URL.createObjectURL(source);
  try {
    const image = document.createElement("img");
    image.src = url;
    await image.decode();
    // A viewBox-only SVG reports 0×0 in some engines. 512 is a size, not a
    // guess about the artwork: an SVG scales, so any positive side renders it
    // faithfully — and the alternative (refusing the copy) is worse.
    return {
      height: image.naturalHeight > 0 ? image.naturalHeight : EXPORT_SVG_FALLBACK_SIDE,
      image,
      release: () => URL.revokeObjectURL(url),
      width: image.naturalWidth > 0 ? image.naturalWidth : EXPORT_SVG_FALLBACK_SIDE,
    };
  } catch (error) {
    URL.revokeObjectURL(url);
    throw error;
  }
}

async function decodeRasterForExport(source: Blob): Promise<DecodedExportImage> {
  if (typeof createImageBitmap === "function") {
    const bitmap = await createImageBitmap(source);
    return {
      height: bitmap.height,
      image: bitmap,
      release: () => bitmap.close(),
      width: bitmap.width,
    };
  }
  const url = URL.createObjectURL(source);
  try {
    const image = document.createElement("img");
    image.src = url;
    await image.decode();
    if (image.naturalWidth <= 0 || image.naturalHeight <= 0) {
      // Unlike an SVG, a raster with no intrinsic size did not decode — there
      // is nothing to fall back TO.
      throw new Error("decoded image has no intrinsic size");
    }
    return {
      height: image.naturalHeight,
      image,
      release: () => URL.revokeObjectURL(url),
      width: image.naturalWidth,
    };
  } catch (error) {
    URL.revokeObjectURL(url);
    throw error;
  }
}

async function drawToPngBlob(
  image: CanvasImageSource,
  width: number,
  height: number,
): Promise<Blob> {
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(width));
  canvas.height = Math.max(1, Math.round(height));
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("2d context unavailable for png export");
  }
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  return await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob);
      } else {
        reject(new Error("canvas produced no png"));
      }
    }, "image/png");
  });
}
