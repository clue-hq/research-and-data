"use client";

import {
  AlignCenter,
  AlignJustify,
  AlignLeft,
  AlignRight,
  AlignVerticalJustifyCenter,
  AlignVerticalJustifyEnd,
  AlignVerticalJustifyStart,
  Italic,
  Strikethrough,
  Underline
} from "lucide-react";
import type { BrandTokenCatalog, Node, Operation, TextAlign, TextTransform, VerticalAlign } from "@/engine/contracts";
import { updateNodeFills, updateTextNode } from "@/engine/operations";
import { ColorSwatchControl } from "./ColorSwatchControl";

/** Contextual typography toolbar shown above the canvas while a text node is
 * selected — the fast twin of the inspector's Text section. Fields in,
 * operations out; whether an edit is allowed is the shell's decision. */

const FONT_WEIGHTS: Array<{ value: number; label: string }> = [
  { value: 100, label: "Thin" },
  { value: 200, label: "Extra Light" },
  { value: 300, label: "Light" },
  { value: 400, label: "Regular" },
  { value: 500, label: "Medium" },
  { value: 600, label: "Semi Bold" },
  { value: 700, label: "Bold" },
  { value: 800, label: "Extra Bold" },
  { value: 900, label: "Black" }
];

const ALIGN_OPTIONS: Array<{ value: TextAlign; label: string; Icon: typeof AlignLeft }> = [
  { value: "left", label: "Align left", Icon: AlignLeft },
  { value: "center", label: "Align center", Icon: AlignCenter },
  { value: "right", label: "Align right", Icon: AlignRight },
  { value: "justify", label: "Justify", Icon: AlignJustify }
];

const VALIGN_OPTIONS: Array<{ value: VerticalAlign; label: string; Icon: typeof AlignLeft }> = [
  { value: "top", label: "Vertical align top", Icon: AlignVerticalJustifyStart },
  { value: "center", label: "Vertical align center", Icon: AlignVerticalJustifyCenter },
  { value: "bottom", label: "Vertical align bottom", Icon: AlignVerticalJustifyEnd }
];

export function TextToolbar({
  selectedNode,
  onOperation,
  brandTokens
}: {
  selectedNode: Node | null;
  onOperation: (operation: Operation) => void;
  brandTokens?: BrandTokenCatalog | null;
}) {
  if (!selectedNode || selectedNode.kind.kind !== "text") {
    return null;
  }
  const text = selectedNode.kind;
  const disabled = selectedNode.locked;
  // D6: valign is a no-op on a hug-height box (zero slack) — disable the group
  // with an explanatory tooltip rather than offering a dead knob.
  const hugHeight = selectedNode.size.height.kind === "hug";
  const valign = text.valign ?? "top";
  const knownWeight = FONT_WEIGHTS.some((weight) => weight.value === text.font_weight);

  const commitNumber = (raw: string, apply: (value: number) => Operation) => {
    const value = Number(raw);
    if (Number.isFinite(value)) {
      onOperation(apply(value));
    }
  };

  return (
    <div className="text-toolbar" role="toolbar" aria-label="Text formatting" data-testid="text-toolbar">
      <input
        className="text-toolbar-family"
        aria-label="Font family"
        value={text.font_family}
        disabled={disabled}
        onChange={(event) => onOperation(updateTextNode(selectedNode, { font_family: event.target.value }))}
      />
      <select
        className="text-toolbar-weight"
        aria-label="Font weight"
        value={text.font_weight}
        disabled={disabled}
        onChange={(event) =>
          onOperation(updateTextNode(selectedNode, { font_weight: Math.round(Number(event.target.value)) }))
        }
      >
        {knownWeight ? null : <option value={text.font_weight}>{text.font_weight}</option>}
        {FONT_WEIGHTS.map((weight) => (
          <option key={weight.value} value={weight.value}>
            {weight.label}
          </option>
        ))}
      </select>
      <input
        className="text-toolbar-number size"
        type="number"
        aria-label="Font size"
        value={Number.isFinite(text.font_size) ? text.font_size : 0}
        min={1}
        disabled={disabled}
        onChange={(event) =>
          commitNumber(event.target.value, (value) =>
            updateTextNode(selectedNode, { font_size: Math.max(1, value) })
          )
        }
      />
      <div className="text-toolbar-align" role="group" aria-label="Text alignment">
        {ALIGN_OPTIONS.map(({ value, label, Icon }) => (
          <button
            key={value}
            type="button"
            className={text.align === value ? "active" : undefined}
            aria-label={label}
            aria-pressed={text.align === value}
            disabled={disabled}
            onClick={() => onOperation(updateTextNode(selectedNode, { align: value }))}
          >
            <Icon aria-hidden size={14} />
          </button>
        ))}
      </div>
      <div className="text-toolbar-align" role="group" aria-label="Vertical alignment">
        {VALIGN_OPTIONS.map(({ value, label, Icon }) => (
          <button
            key={value}
            type="button"
            className={valign === value ? "active" : undefined}
            aria-label={label}
            aria-pressed={valign === value}
            disabled={disabled || hugHeight}
            title={hugHeight ? "No effect with hug height" : undefined}
            onClick={() => onOperation(updateTextNode(selectedNode, { valign: value }))}
          >
            <Icon aria-hidden size={14} />
          </button>
        ))}
      </div>
      <div className="text-toolbar-align" role="group" aria-label="Text decoration">
        <button
          type="button"
          className={text.italic ? "active" : undefined}
          aria-label="Italic"
          aria-pressed={text.italic ?? false}
          disabled={disabled}
          onClick={() => onOperation(updateTextNode(selectedNode, { italic: !text.italic }))}
        >
          <Italic aria-hidden size={14} />
        </button>
        <button
          type="button"
          className={text.underline ? "active" : undefined}
          aria-label="Underline"
          aria-pressed={text.underline ?? false}
          disabled={disabled}
          onClick={() => onOperation(updateTextNode(selectedNode, { underline: !text.underline }))}
        >
          <Underline aria-hidden size={14} />
        </button>
        <button
          type="button"
          className={text.strikethrough ? "active" : undefined}
          aria-label="Strikethrough"
          aria-pressed={text.strikethrough ?? false}
          disabled={disabled}
          onClick={() => onOperation(updateTextNode(selectedNode, { strikethrough: !text.strikethrough }))}
        >
          <Strikethrough aria-hidden size={14} />
        </button>
      </div>
      <select
        className="text-toolbar-weight"
        aria-label="Text case"
        value={text.text_transform ?? "none"}
        disabled={disabled}
        onChange={(event) =>
          onOperation(updateTextNode(selectedNode, { text_transform: event.target.value as TextTransform }))
        }
      >
        <option value="none">Case</option>
        <option value="uppercase">UPPER</option>
        <option value="lowercase">lower</option>
        <option value="title">Title</option>
      </select>
      <label className="text-toolbar-metric">
        <span aria-hidden>LH</span>
        <input
          className="text-toolbar-number"
          type="number"
          aria-label="Line height"
          value={text.line_height ?? 1.2}
          min={0.1}
          step={0.05}
          disabled={disabled}
          onChange={(event) =>
            commitNumber(event.target.value, (value) =>
              updateTextNode(selectedNode, { line_height: Math.max(0.1, value) })
            )
          }
        />
      </label>
      <label className="text-toolbar-metric">
        <span aria-hidden>LS</span>
        <input
          className="text-toolbar-number"
          type="number"
          aria-label="Letter spacing"
          value={text.letter_spacing ?? 0}
          step={0.25}
          disabled={disabled}
          onChange={(event) =>
            commitNumber(event.target.value, (value) => updateTextNode(selectedNode, { letter_spacing: value }))
          }
        />
      </label>
      {text.style_token ? (
        <span
          className="text-toolbar-token-chip"
          data-testid="text-toolbar-token-chip"
          title="Bound to a brand type role — raw typography edits detach it"
        >
          {text.style_token}
        </span>
      ) : null}
      <ColorSwatchControl
        node={selectedNode}
        brandTokens={brandTokens}
        label="Text color"
        onEdit={(fills) => onOperation(updateNodeFills(selectedNode, fills))}
      />
    </div>
  );
}
