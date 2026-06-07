"use client";

import { Tags, Unlink } from "lucide-react";
import type { ContentType, Node, NodeId, Operation, OverflowPolicy, Scene, Slot } from "@/engine/contracts";
import { defaultTextSlot, removeSlot, unbindNodeFromSlot, upsertSlot } from "@/engine/operations";
import { slotByNode } from "@/engine/sceneQueries";

interface SlotInspectorProps {
  scene: Scene;
  selectedNode: Node;
  selectedNodeId: NodeId | null;
  onOperation: (operation: Operation) => void;
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

export function SlotInspector({ scene, selectedNode, selectedNodeId, onOperation }: SlotInspectorProps) {
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
          slot={slot}
          locked={selectedNode.locked}
          onChange={(nextSlot) => onOperation(upsertSlot(nextSlot))}
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

function SlotEditor({
  slot,
  locked,
  onChange,
  onUnbind
}: {
  slot: Slot;
  locked: boolean;
  onChange: (slot: Slot) => void;
  onUnbind: () => void;
}) {
  const update = (patch: Partial<Slot>) => onChange({ ...slot, ...patch });

  return (
    <div className="slot-editor">
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
      <button type="button" className="danger-button" disabled={locked} onClick={onUnbind}>
        <Unlink aria-hidden size={15} />
        Unmark slot
      </button>
    </div>
  );
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
