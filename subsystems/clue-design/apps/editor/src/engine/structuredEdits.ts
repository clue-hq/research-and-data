import type { Node, NodePatch, Operation, Scene, TextNode } from "./contracts";
import { nodePatch, pagePatch, set, unchanged, clear } from "./operations";

/**
 * TypeScript wrapper for the Phase D structured-edit wire format.
 *
 * The backend `/documents/{id}/edits` route is the authority for committed
 * editor edits (Phase D Decision 8); the helpers here exist for two jobs
 * only: building the exact JSON the Rust `StructuredEditInstruction`
 * deserializes, and producing optimistic operations for instant local
 * preview that must match the Rust builders byte-for-byte. The parity
 * fixtures in `fixtures/edit-parity/cases.json` (asserted from both
 * languages in CI) keep the two implementations from drifting.
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

/**
 * Optimistic local operations for an edit, mirroring the Rust builders'
 * semantics exactly: text patches merge into the node's current text kind,
 * and render-affecting changes clear stale computed geometry. Only the
 * edits the editor previews optimistically are implemented; everything
 * else waits for the server response.
 */
export function optimisticOperations(scene: Scene, edit: StructuredEdit): Operation[] {
  if (edit.kind === "delete") {
    const target = edit.target as EditTarget;
    if (target.kind === "node") {
      return [{ kind: "remove_node", node_id: target.id } as Operation];
    }
    return [];
  }
  if (edit.kind !== "modify") {
    return [];
  }
  const target = edit.target as EditTarget;
  const patch = edit.patch as { kind: string; value: Record<string, unknown> };
  if (target.kind === "page" && patch.kind === "page") {
    return [
      {
        kind: "update_page",
        page_id: target.id,
        patch: pagePatch(patch.value as never)
      } as Operation
    ];
  }
  if (target.kind === "node" && patch.kind === "node") {
    const node = scene.nodes[target.id];
    if (!node) {
      return [];
    }
    const textInput = (patch.value as { text?: Record<string, { kind: string; value?: unknown }> })
      .text;
    if (!textInput || node.kind.kind !== "text") {
      return [];
    }
    const merged = { ...(node.kind as { kind: "text" } & TextNode) };
    for (const [field, fieldPatch] of Object.entries(textInput)) {
      if (fieldPatch.kind === "set") {
        (merged as Record<string, unknown>)[field] = fieldPatch.value;
      }
    }
    const operationPatch: NodePatch = nodePatch({
      kind: set(merged),
      computed: clear()
    });
    return [
      {
        kind: "update_node",
        node_id: target.id,
        patch: operationPatch
      } as Operation
    ];
  }
  return [];
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
  const response = await fetch(`${apiBaseUrl}/documents/${documentId}/edits`, {
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
  const response = await fetch(
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
  const response = await fetch(`${apiBaseUrl}/documents/${documentId}/${action}`, {
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
  const response = await fetch(
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
