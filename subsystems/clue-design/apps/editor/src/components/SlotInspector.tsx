"use client";

import { Tags, Unlink } from "lucide-react";
import type { ContentType, Node, NodeId, Operation, OverflowPolicy, PageId, Scene, Slot } from "@/engine/contracts";
import { defaultTextSlot, removeSlot, unbindNodeFromSlot, updateTextNode, upsertSlot } from "@/engine/operations";
import { nodeDisplayName, slotBoundNodeSummaries, slotByNode } from "@/engine/sceneQueries";

interface SlotInspectorProps {
  scene: Scene;
  selectedNode: Node;
  selectedNodeId: NodeId | null;
  onOperation: (operation: Operation) => void;
  onOperations?: (operations: Operation[]) => void;
}

const contentTypes: ContentType[] = [
  "text_short",
  "text_long",
  "rich_text_limited",
  "number_stat",
  "date",
  "image",
  "logo",
  "url_qr",
  "list",
  "repeater_group",
  "table_like"
];

export function SlotInspector({ scene, selectedNode, selectedNodeId, onOperation, onOperations }: SlotInspectorProps) {
  const slot = slotByNode(scene, selectedNodeId);

  const markAsSlot = () => {
    const fallbackKey = selectedNode.name
      ? selectedNode.name.toLowerCase().replaceAll(/\s+/g, ".")
      : selectedNode.id.replace(/^node_/, "");
    const placeholder = selectedNode.kind.kind === "text" ? selectedNode.kind.content : null;
    onOperation(defaultSlotOperation(selectedNode.id, fallbackKey, selectedNode.name ?? fallbackKey, placeholder));
  };

  return (
    <section className="inspector-section">
      <div className="section-heading">
        <Tags aria-hidden size={15} />
        Slot
      </div>
      {!slot ? (
        <div className="empty-card">
          <p>No slot is bound to this node.</p>
          <button type="button" disabled={selectedNode.locked} onClick={markAsSlot}>
            <Tags aria-hidden size={15} />
            Mark slot
          </button>
        </div>
      ) : (
        <SlotEditor
          scene={scene}
          slot={slot}
          locked={selectedNode.locked}
          onChange={(nextSlot) => onOperation(upsertSlot(nextSlot))}
          onApplyPreview={(value) => {
            const operations = previewTextTargets(scene, slot).map((node) => updateTextNode(node, { content: value }));
            if (operations.length === 0) {
              return;
            }
            if (onOperations) {
              onOperations(operations);
            } else {
              operations.forEach((operation) => onOperation(operation));
            }
          }}
          onUnbind={() => {
            onOperation(unbindNodeFromSlot(slot.id, selectedNode.id));
            if (slot.bound_nodes.length <= 1) {
              onOperation(removeSlot(slot.id));
            }
          }}
        />
      )}
    </section>
  );
}

export function SlotOverview({ scene, activePageId }: { scene: Scene; activePageId: PageId | null }) {
  const entries = Object.values(scene.slots)
    .map((slot) => ({
      slot,
      boundNodes: slotBoundNodeSummaries(scene, slot)
    }))
    .filter(({ slot, boundNodes }) => {
      if (!activePageId) {
        return true;
      }
      if (slot.scope.kind === "document") {
        return true;
      }
      if (slot.scope.kind === "page" && slot.scope.id === activePageId) {
        return true;
      }
      return boundNodes.some((node) => node.pageId === activePageId);
    })
    .sort((left, right) => left.slot.key.localeCompare(right.slot.key));

  return (
    <section className="slot-overview" aria-label="Page slot overview">
      <div className="section-heading nested-heading">Slots on this page</div>
      {entries.length === 0 ? (
        <p className="muted">No slots are bound to this page.</p>
      ) : (
        <ul className="slot-overview-list">
          {entries.map(({ slot, boundNodes }) => (
            <li key={slot.id}>
              <div>
                <strong>{slot.key}</strong>
                <span>
                  {slot.required ? "Required" : "Optional"} · {slot.content_type} · {overflowLabel(slot.overflow)}
                </span>
              </div>
              {previewValues(slot).length > 0 ? (
                <small>
                  Preview {previewValues(slot).map((preview) => `${preview.kind}: ${preview.value}`).join(" · ")}
                </small>
              ) : null}
              {boundNodes.length > 0 ? (
                <small>
                  Bound to{" "}
                  {boundNodes
                    .map((node) => `${node.pageName ?? "No page"} / ${node.nodeName} (${node.nodeId})`)
                    .join(", ")}
                </small>
              ) : (
                <small>Not bound to any node.</small>
              )}
              <SlotReadinessList notes={slotReadinessNotes(scene, slot)} compact />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function SlotEditor({
  scene,
  slot,
  locked,
  onChange,
  onApplyPreview,
  onUnbind
}: {
  scene: Scene;
  slot: Slot;
  locked: boolean;
  onChange: (slot: Slot) => void;
  onApplyPreview: (value: string) => void;
  onUnbind: () => void;
}) {
  const update = (patch: Partial<Slot>) => onChange({ ...slot, ...patch });
  const boundNodes = slotBoundNodeSummaries(scene, slot);
  const previews = previewValues(slot);
  const readiness = slotReadinessNotes(scene, slot);
  const textPreviewTargets = previewTextTargets(scene, slot);
  const canApplyTextPreview = !locked && textPreviewTargets.length > 0;

  return (
    <div className="slot-editor">
      <div className="slot-summary-grid" aria-label="Slot summary">
        <span>Scope</span>
        <strong>{scopeLabel(scene, slot)}</strong>
        <span>Status</span>
        <strong>{slot.required ? "Required" : "Optional"}</strong>
        <span>Overflow</span>
        <strong>{overflowLabel(slot.overflow)}</strong>
        <span>Cardinality</span>
        <strong>
          {slot.cardinality.min_items}-
          {slot.cardinality.max_items === null ? "many" : slot.cardinality.max_items}
        </strong>
        <span>Editability</span>
        <strong>{slot.editability}</strong>
      </div>
      <SlotReadinessList notes={readiness} />
      <div className="slot-preview-card">
        <strong>Content preview</strong>
        {previews.length > 0 ? (
          <ul>
            {previews.map((preview) => (
              <li key={`${preview.kind}-${preview.value}`}>
                <span>{preview.kind}</span>
                <code>{preview.value}</code>
                <button
                  type="button"
                  className="secondary-action"
                  disabled={!canApplyTextPreview}
                  onClick={() => onApplyPreview(preview.value)}
                >
                  Apply to {textPreviewTargets.length === 1 ? "text node" : "text nodes"}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No placeholder, sample, or worst-case fixture is configured for this slot.</p>
        )}
        {previews.length > 0 && textPreviewTargets.length === 0 ? (
          <p className="muted">Fixture preview can be applied to text-bound slots. Image and logo previews wait for asset runtime.</p>
        ) : null}
      </div>
      <div className="slot-preview-card">
        <strong>Bound nodes</strong>
        {boundNodes.length > 0 ? (
          <ul>
            {boundNodes.map((node) => (
              <li key={node.nodeId}>
                <span>{node.pageName ?? "No page"}</span>
                <code>
                  {node.nodeName} ({node.nodeId})
                </code>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No nodes are bound to this slot.</p>
        )}
      </div>
      <label className="field">
        <span>Key</span>
        <input value={slot.key} disabled={locked} onChange={(event) => update({ key: event.target.value })} />
      </label>
      <label className="field">
        <span>Label</span>
        <input value={slot.label} disabled={locked} onChange={(event) => update({ label: event.target.value })} />
      </label>
      <div className="field-grid two">
        <label className="field">
          <span>Type</span>
          <select
            value={slot.content_type}
            disabled={locked}
            onChange={(event) => update({ content_type: event.target.value as ContentType })}
          >
            {contentTypes.map((contentType) => (
              <option key={contentType} value={contentType}>
                {contentType}
              </option>
            ))}
          </select>
        </label>
        <label className="toggle-field">
          <input
            type="checkbox"
            checked={slot.required}
            disabled={locked}
            onChange={(event) => update({ required: event.target.checked })}
          />
          Required
        </label>
      </div>
      <label className="field">
        <span>Placeholder</span>
        <input
          value={slot.placeholder ?? ""}
          disabled={locked}
          onChange={(event) => update({ placeholder: event.target.value || null })}
        />
      </label>
      <label className="field">
        <span>Sample fixtures</span>
        <textarea
          value={slot.validation.samples.join("\n")}
          rows={3}
          disabled={locked}
          onChange={(event) =>
            update({
              validation: {
                ...slot.validation,
                samples: splitFixtureLines(event.target.value)
              }
            })
          }
        />
      </label>
      <label className="field">
        <span>Worst-case fixture</span>
        <input
          value={slot.validation.worst_case ?? ""}
          disabled={locked}
          onChange={(event) =>
            update({
              validation: {
                ...slot.validation,
                worst_case: event.target.value || null
              }
            })
          }
        />
      </label>
      <div className="field-grid two">
        <NumberField
          label="Fixture Max Length"
          value={slot.validation.max_length ?? 0}
          min={0}
          disabled={locked}
          onCommit={(value) =>
            update({
              validation: {
                ...slot.validation,
                max_length: value > 0 ? Math.round(value) : null
              }
            })
          }
        />
        <NumberField
          label="Formatting Max Length"
          value={slot.formatting.max_length ?? 0}
          min={0}
          disabled={locked}
          onCommit={(value) =>
            update({
              formatting: {
                ...slot.formatting,
                max_length: value > 0 ? Math.round(value) : null
              }
            })
          }
        />
      </div>
      <label className="field">
        <span>Overflow</span>
        <select
          value={slot.overflow.kind}
          disabled={locked}
          onChange={(event) => update({ overflow: overflowFromKind(event.target.value) })}
        >
          <option value="error">Error</option>
          <option value="shrink_font">Shrink font</option>
          <option value="wrap">Wrap</option>
          <option value="ellipsis">Ellipsis</option>
          <option value="clip">Clip</option>
          <option value="expand_container">Expand container</option>
          <option value="ask_agent_to_repair">Ask agent to repair</option>
        </select>
      </label>
      <div className="slot-summary-grid" aria-label="Slot constraints">
        <span>Max length</span>
        <strong>{slot.formatting.max_length ?? slot.validation.max_length ?? "None"}</strong>
        <span>Pattern</span>
        <strong>{slot.formatting.allowed_pattern ?? "None"}</strong>
        <span>Preserve case</span>
        <strong>{slot.formatting.preserve_case ? "Yes" : "No"}</strong>
        <span>Conditional</span>
        <strong>{slot.conditional ? slot.conditional.expression : "None"}</strong>
        <span>Repeater</span>
        <strong>{slot.repeater ? `${slot.repeater.item_slot_key} (${slot.repeater.reflow})` : "None"}</strong>
        <span>Image policy</span>
        <strong>{slot.image_policy ? imagePolicyLabel(slot) : "None"}</strong>
      </div>
      <button type="button" className="danger-button" disabled={locked} onClick={onUnbind}>
        <Unlink aria-hidden size={15} />
        Unmark slot
      </button>
    </div>
  );
}

interface SlotReadinessNote {
  severity: "error" | "warning" | "advice";
  code: string;
  message: string;
}

function SlotReadinessList({
  notes,
  compact = false
}: {
  notes: SlotReadinessNote[];
  compact?: boolean;
}) {
  if (notes.length === 0) {
    return compact ? null : <p className="slot-readiness-ok">Slot readiness OK.</p>;
  }
  return (
    <ul className={compact ? "slot-readiness-list compact" : "slot-readiness-list"} aria-label="Slot readiness">
      {notes.map((note) => (
        <li key={`${note.code}-${note.message}`} className={note.severity}>
          <strong>{note.code}</strong>
          <span>{note.message}</span>
        </li>
      ))}
    </ul>
  );
}

function slotReadinessNotes(scene: Scene, slot: Slot): SlotReadinessNote[] {
  const notes: SlotReadinessNote[] = [];

  if (!slotScopeExists(scene, slot)) {
    notes.push({
      severity: "error",
      code: "SLOT_SCOPE_MISSING",
      message: `Slot scope ${scopeLabel(scene, slot)} cannot be resolved.`
    });
  }

  if (slot.required && slot.bound_nodes.length === 0) {
    notes.push({
      severity: "error",
      code: "SLOT_REQUIRED_UNBOUND",
      message: "Required slot is not bound to any node."
    });
  }

  for (const nodeId of slot.bound_nodes) {
    const node = scene.nodes[nodeId];
    if (!node) {
      notes.push({
        severity: "error",
        code: "SLOT_BOUND_NODE_MISSING",
        message: `Slot is bound to missing node ${nodeId}.`
      });
      continue;
    }

    if (isImageLikeSlot(slot) && node.kind.kind !== "image") {
      notes.push({
        severity: "warning",
        code: "SLOT_IMAGE_NODE_KIND",
        message: `${slot.key} expects image/logo content but is bound to ${node.kind.kind}.`
      });
    }

    if (isImageLikeSlot(slot) && node.kind.kind === "image") {
      const asset = scene.assets[node.kind.asset_id];
      if (!asset || asset.status !== "ready") {
        notes.push({
          severity: "warning",
          code: "SLOT_IMAGE_ASSET_NOT_READY",
          message: `${slot.key} image asset ${node.kind.asset_id} is missing or not ready.`
        });
      } else if (slot.image_policy?.min_dpi && imageAssetDpi(asset) !== null && imageAssetDpi(asset)! < slot.image_policy.min_dpi) {
        notes.push({
          severity: "warning",
          code: "SLOT_IMAGE_DPI_LOW",
          message: `${slot.key} image asset is below ${slot.image_policy.min_dpi} DPI.`
        });
      }
    }
  }

  if (slot.required && previewValues(slot).length === 0) {
    notes.push({
      severity: "warning",
      code: "SLOT_REQUIRED_NO_FIXTURE",
      message: "Required slot has no placeholder, sample, or worst-case fixture for approval checks."
    });
  }

  const maxLength = slot.formatting.max_length ?? slot.validation.max_length;
  if (maxLength !== null) {
    for (const preview of previewValues(slot)) {
      if (preview.value.length > maxLength) {
        notes.push({
          severity: "warning",
          code: "SLOT_FIXTURE_EXCEEDS_MAX_LENGTH",
          message: `${preview.kind} fixture for ${slot.key} is ${preview.value.length} characters, above the configured max length ${maxLength}.`
        });
      }
    }
  }

  if (slot.overflow.kind === "clip") {
    notes.push({
      severity: "advice",
      code: "SLOT_OVERFLOW_CLIPS",
      message: "Slot overflow clips content; verify personalized copy in preview before approval."
    });
  }

  return dedupeReadinessNotes(notes);
}

function slotScopeExists(scene: Scene, slot: Slot): boolean {
  switch (slot.scope.kind) {
    case "document":
      return true;
    case "page":
      return Boolean(scene.pages[slot.scope.id]);
    case "node":
    case "group":
      return Boolean(scene.nodes[slot.scope.id]);
  }
}

function isImageLikeSlot(slot: Slot): boolean {
  return slot.content_type === "image" || slot.content_type === "logo";
}

function imageAssetDpi(asset: Scene["assets"][string]): number | null {
  if (asset.raster?.dpi_x || asset.raster?.dpi_y) {
    return Math.min(asset.raster.dpi_x ?? asset.raster.dpi_y ?? 0, asset.raster.dpi_y ?? asset.raster.dpi_x ?? 0);
  }
  if (asset.logo?.dpi_x || asset.logo?.dpi_y) {
    return Math.min(asset.logo.dpi_x ?? asset.logo.dpi_y ?? 0, asset.logo.dpi_y ?? asset.logo.dpi_x ?? 0);
  }
  return null;
}

function dedupeReadinessNotes(notes: SlotReadinessNote[]): SlotReadinessNote[] {
  const seen = new Set<string>();
  return notes.filter((note) => {
    const key = `${note.code}:${note.message}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function scopeLabel(scene: Scene, slot: Slot): string {
  switch (slot.scope.kind) {
    case "document":
      return "Document";
    case "page":
      return scene.pages[slot.scope.id]?.name ?? `Missing page ${slot.scope.id}`;
    case "node":
    case "group": {
      const node = scene.nodes[slot.scope.id];
      return node ? `${nodeDisplayName(node)} (${slot.scope.kind})` : `Missing ${slot.scope.kind} ${slot.scope.id}`;
    }
  }
}

function overflowLabel(overflow: OverflowPolicy): string {
  switch (overflow.kind) {
    case "shrink_font":
      return `Shrink font ${overflow.min_font_size}-${overflow.max_font_size ?? "auto"}`;
    case "wrap":
      return `Wrap${overflow.max_lines ? ` ${overflow.max_lines} lines` : ""}`;
    case "ask_agent_to_repair":
      return "Ask agent to repair";
    case "expand_container":
      return "Expand container";
    case "ellipsis":
      return "Ellipsis";
    case "clip":
      return "Clip";
    case "error":
      return "Error";
  }
}

function previewValues(slot: Slot): Array<{ kind: string; value: string }> {
  const values: Array<{ kind: string; value: string }> = [];
  if (slot.placeholder) {
    values.push({ kind: "Placeholder", value: slot.placeholder });
  }
  for (const sample of slot.validation.samples) {
    values.push({ kind: "Sample", value: sample });
  }
  if (slot.validation.worst_case) {
    values.push({ kind: "Worst case", value: slot.validation.worst_case });
  }
  return values;
}

function previewTextTargets(scene: Scene, slot: Slot): Node[] {
  return slot.bound_nodes.flatMap((nodeId) => {
    const node = scene.nodes[nodeId];
    if (!node || node.locked || node.kind.kind !== "text") {
      return [];
    }
    return [node];
  });
}

function imagePolicyLabel(slot: Slot): string {
  const policy = slot.image_policy;
  if (!policy) {
    return "None";
  }
  return `${policy.fit}${policy.min_dpi ? `, ${policy.min_dpi} dpi min` : ""}`;
}

function defaultSlotOperation(nodeId: NodeId, slotKey: string, label: string, placeholder: string | null): Operation {
  return upsertSlot(
    defaultTextSlot(nodeId, sanitizeSlotKey(slotKey), label, placeholder, {
      kind: "error"
    })
  );
}

function sanitizeSlotKey(value: string): string {
  return (
    value
      .trim()
      .toLowerCase()
      .replaceAll(/[^a-z0-9_.-]+/g, ".")
      .replaceAll(/^\.+|\.+$/g, "") || "content.placeholder"
  );
}

function overflowFromKind(kind: string): OverflowPolicy {
  switch (kind) {
    case "shrink_font":
      return {
        kind: "shrink_font",
        min_font_size: 10,
        max_font_size: null
      };
    case "wrap":
      return {
        kind: "wrap",
        max_lines: null
      };
    case "clip":
      return {
        kind: "clip"
      };
    case "ellipsis":
      return {
        kind: "ellipsis"
      };
    case "expand_container":
      return {
        kind: "expand_container"
      };
    case "ask_agent_to_repair":
      return {
        kind: "ask_agent_to_repair"
      };
    default:
      return {
        kind: "error"
      };
  }
}

function splitFixtureLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function NumberField({
  label,
  value,
  min,
  disabled,
  onCommit
}: {
  label: string;
  value: number;
  min?: number;
  disabled?: boolean;
  onCommit: (value: number) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        min={min}
        disabled={disabled}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (Number.isFinite(next)) {
            onCommit(min !== undefined ? Math.max(min, next) : next);
          }
        }}
      />
    </label>
  );
}
