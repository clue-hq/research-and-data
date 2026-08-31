import type { Effect, Fill, Node, Operation, Scene, Stroke } from "./contracts";
import { lumenFetch } from "./editorConfig";

/**
 * TypeScript wrapper for the Phase D structured-edit wire format.
 *
 * The backend `/documents/{id}/edits` route is the authority for committed
 * editor edits (Phase D Decision 8). Since Track E W4 these helpers build
 * wire-format JSON ONLY — optimistic application runs in the WASM engine
 * (`WasmEngine.applyStructuredEdit`), which routes through the same
 * `lumen_core::build_structured_edit_batch` the server uses, so byte
 * parity is by construction. `fixtures/edit-parity/cases.json` remains the
 * pinned smoke contract (asserted by the Rust helper test, the wasm engine
 * tests, and the wire-format smoke test here).
 */

export type EditTarget =
  | { kind: "document" }
  | { kind: "page"; id: string }
  | { kind: "node"; id: string }
  | { kind: "slot"; id: string }
  | { kind: "slot_key"; id: string }
  | { kind: "asset"; id: string }
  | { kind: "export_profile"; id: string };

export interface EditScope {
  mode: "strict" | "advisory";
  allowed: EditTarget[];
}

export interface TextEditPatchInput {
  content?: string;
  font_size?: number;
  font_weight?: number;
}

export interface NodeModifyInput {
  text?: TextEditPatchInput;
}

/**
 * Per-entry stack edit (Effects Contract V0): the exact wire shape of the
 * Rust `StackEntryEdit<T, I>` enum. Entries are addressed by stable
 * PaintId/EffectId so unrelated entries are never touched.
 */
export type StackEntryEdit<T> =
  | { kind: "set"; id: string; value: T }
  | { kind: "add"; entry: T; index?: number }
  | { kind: "remove"; id: string }
  | { kind: "reorder"; id: string; index: number };

export interface NodeStackEditsInput {
  fillEdits?: StackEntryEdit<Fill>[];
  strokeEdits?: StackEntryEdit<Stroke>[];
  effectEdits?: StackEntryEdit<Effect>[];
}

export type StructuredEdit = Record<string, unknown> & { kind: string };

export function modifyNodeEdit(nodeId: string, input: NodeModifyInput): StructuredEdit {
  const text: Record<string, unknown> = {};
  if (input.text?.content !== undefined) {
    text.content = { kind: "set", value: input.text.content };
  }
  if (input.text?.font_size !== undefined) {
    text.font_size = { kind: "set", value: input.text.font_size };
  }
  if (input.text?.font_weight !== undefined) {
    text.font_weight = { kind: "set", value: input.text.font_weight };
  }
  return {
    kind: "modify",
    target: { kind: "node", id: nodeId },
    patch: { kind: "node", value: { text } }
  };
}

export function modifyNodeStacksEdit(nodeId: string, input: NodeStackEditsInput): StructuredEdit {
  const value: Record<string, unknown> = {};
  if (input.fillEdits?.length) {
    value.fill_edits = input.fillEdits;
  }
  if (input.strokeEdits?.length) {
    value.stroke_edits = input.strokeEdits;
  }
  if (input.effectEdits?.length) {
    value.effect_edits = input.effectEdits;
  }
  return {
    kind: "modify",
    target: { kind: "node", id: nodeId },
    patch: { kind: "node", value }
  };
}

export function modifyPageNameEdit(pageId: string, name: string): StructuredEdit {
  return {
    kind: "modify",
    target: { kind: "page", id: pageId },
    patch: { kind: "page", value: { name: { kind: "set", value: name } } }
  };
}

export function deleteEdit(target: EditTarget): StructuredEdit {
  return { kind: "delete", target };
}

export function moveBeforeEdit(nodeId: string, anchor: string): StructuredEdit {
  return { kind: "move_before", node_id: nodeId, anchor };
}

export function moveAfterEdit(nodeId: string, anchor: string): StructuredEdit {
  return { kind: "move_after", node_id: nodeId, anchor };
}

export function archiveAssetEdit(assetId: string): StructuredEdit {
  return { kind: "archive_asset", asset_id: assetId };
}

/** Phase 1c freehand: pin a node at its solved box (zero-motion detach). */
export function detachToFreehandEdit(nodeId: string): StructuredEdit {
  return { kind: "detach_to_freehand", node_id: nodeId };
}

/** Phase 1c freehand: return a pinned node to solver ownership. */
export function reattachToLayoutEdit(nodeId: string): StructuredEdit {
  return { kind: "reattach_to_layout", node_id: nodeId };
}

/** Phase 1c freehand: flip a container between stacked and free children. */
export function convertContainerLayoutEdit(
  nodeId: string,
  layoutMode: "stack" | "free"
): StructuredEdit {
  return { kind: "convert_container_layout", node_id: nodeId, layout_mode: layoutMode };
}

/** Handoff-absolute: bake every Stack container to Free in one zero-motion
 * batch — after an agent turn the human edits pure absolute. Idempotent
 * (empty batch when nothing is left to freeze). */
export function freezeLayoutEdit(): StructuredEdit {
  return { kind: "freeze_layout" };
}

/** Phase 4b arrange: wrap same-parent siblings in a new Group container.
 * The caller mints `groupId` so the edit replays deterministically. */
export function groupEdit(nodeIds: string[], groupId: string, name?: string): StructuredEdit {
  return {
    kind: "group",
    node_ids: nodeIds,
    group_id: groupId,
    ...(name !== undefined ? { name } : {})
  };
}

/** Phase 4b arrange: dissolve a container into its parent, keeping child
 * order and geometry. `allowLayout` opts into ungrouping an auto-layout
 * container (destroys its layout semantics) — defaults to false. */
export function ungroupEdit(nodeId: string, allowLayout = false): StructuredEdit {
  return { kind: "ungroup", node_id: nodeId, allow_layout: allowLayout };
}

/** Mints a fresh, scene-unique group id for `groupEdit` — the engine
 * rejects a `group_id` that already exists (see arrange_ops.rs). No
 * existing client-side node-id minting convention covers a fresh id with
 * no source node (unlike page duplication's per-source suffixing), so this
 * wraps `crypto.randomUUID` — never stored bare (frontend-practices §2.8). */
export function mintGroupId(scene: Pick<Scene, "nodes">): string {
  const randomUUID = () => crypto.randomUUID();
  let candidate = `grp-${randomUUID().slice(0, 8)}`;
  while (scene.nodes[candidate]) {
    candidate = `grp-${randomUUID().slice(0, 8)}`;
  }
  return candidate;
}

export function deleteExportProfileEdit(
  name: string,
  replaceWith?: string
): StructuredEdit {
  return {
    kind: "delete_export_profile",
    name,
    ...(replaceWith ? { replace_with: replaceWith } : {})
  };
}

export interface ApplyEditOptions {
  actor?: { kind: string; id?: string | null };
  source?: "editor" | "agent" | "api" | "system";
  scope?: EditScope;
  baseVersion?: number;
  checkpoint?: string;
}

export interface EnvelopeSummary {
  batch_id: string;
  seq: number;
  base_revision: number | null;
  intent: string | null;
  checkpoint_label: string | null;
  touched_targets: EditTarget[];
  invertible: boolean;
}

export async function applyStructuredEdit(
  apiBaseUrl: string,
  documentId: string,
  edit: StructuredEdit,
  options: ApplyEditOptions = {}
): Promise<{ envelope: EnvelopeSummary | null; response: Record<string, unknown> }> {
  const response = await lumenFetch(`${apiBaseUrl}/documents/${documentId}/edits`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      edit,
      actor: options.actor ?? { kind: "editor" },
      source: options.source ?? "editor",
      ...(options.scope ? { scope: options.scope } : {}),
      ...(options.baseVersion !== undefined ? { base_version: options.baseVersion } : {}),
      ...(options.checkpoint ? { checkpoint: options.checkpoint } : {})
    })
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(
      `structured edit failed (${response.status}): ${JSON.stringify(detail)}`
    );
  }
  const payload = (await response.json()) as Record<string, unknown>;
  return { envelope: (payload.envelope as EnvelopeSummary) ?? null, response: payload };
}

export interface HistoryEnvelope extends EnvelopeSummary {
  envelope_version: number;
  actor: { kind: string; id: string | null };
  source: string;
  inverse_operations: Operation[] | null;
  reverts_batch_id: string | null;
  reapplies_batch_id: string | null;
  created_at: string;
}

export async function fetchHistory(
  apiBaseUrl: string,
  documentId: string,
  limit = 50
): Promise<HistoryEnvelope[]> {
  const response = await lumenFetch(
    `${apiBaseUrl}/documents/${documentId}/history?limit=${limit}`
  );
  if (!response.ok) {
    throw new Error(`history fetch failed (${response.status})`);
  }
  const payload = (await response.json()) as { envelopes: HistoryEnvelope[] };
  return payload.envelopes;
}

async function postHistoryAction(
  apiBaseUrl: string,
  documentId: string,
  action: "undo" | "redo",
): Promise<Record<string, unknown>> {
  const response = await lumenFetch(`${apiBaseUrl}/documents/${documentId}/${action}`, {
    method: "POST"
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(`${action} failed (${response.status}): ${JSON.stringify(detail)}`);
  }
  return (await response.json()) as Record<string, unknown>;
}

export function undoDocument(apiBaseUrl: string, documentId: string) {
  return postHistoryAction(apiBaseUrl, documentId, "undo");
}

export function redoDocument(apiBaseUrl: string, documentId: string) {
  return postHistoryAction(apiBaseUrl, documentId, "redo");
}

export async function revertToCheckpoint(
  apiBaseUrl: string,
  documentId: string,
  checkpoint: string
): Promise<Record<string, unknown>> {
  const response = await lumenFetch(
    `${apiBaseUrl}/documents/${documentId}/revert?checkpoint=${encodeURIComponent(checkpoint)}`,
    { method: "POST" }
  );
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(`revert failed (${response.status}): ${JSON.stringify(detail)}`);
  }
  return (await response.json()) as Record<string, unknown>;
}

export type { Node };
