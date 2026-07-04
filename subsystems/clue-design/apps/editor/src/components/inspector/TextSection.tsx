"use client";

import { Type } from "lucide-react";
import type {
  BrandTokenCatalog,
  Node,
  Operation,
  TextAlign,
  TextDirection,
  TextWrap
} from "@/engine/contracts";
import { updateTextNode } from "@/engine/operations";
import { NumberField, TokenSelect } from "./fields";

/** Text content and typography controls for a selected text node. */
export function TextSection({
  selectedNode,
  brandTokens,
  onOperation
}: {
  selectedNode: Node & { kind: Extract<Node["kind"], { kind: "text" }> };
  brandTokens?: BrandTokenCatalog | null;
  onOperation: (operation: Operation) => void;
}) {
  return (
        <section className="inspector-section">
          <div className="section-heading">
            <Type aria-hidden size={15} />
            Text
          </div>
          <label className="field span">
            <span>Content</span>
            <textarea
              value={selectedNode.kind.content}
              rows={4}
              disabled={selectedNode.locked}
              onChange={(event) => onOperation(updateTextNode(selectedNode, { content: event.target.value }))}
            />
          </label>
          <div className="field-grid two">
            <label className="field">
              <span>Family</span>
              <input
                value={selectedNode.kind.font_family}
                disabled={selectedNode.locked}
                onChange={(event) => onOperation(updateTextNode(selectedNode, { font_family: event.target.value }))}
              />
            </label>
            <NumberField
              label="Size"
              value={selectedNode.kind.font_size}
              min={1}
              disabled={selectedNode.locked}
              onCommit={(value) => onOperation(updateTextNode(selectedNode, { font_size: value }))}
            />
            <NumberField
              label="Weight"
              value={selectedNode.kind.font_weight}
              min={100}
              max={900}
              step={100}
              disabled={selectedNode.locked}
              onCommit={(value) => onOperation(updateTextNode(selectedNode, { font_weight: Math.round(value) }))}
            />
            <label className="field">
              <span>Align</span>
              <select
                value={selectedNode.kind.align}
                disabled={selectedNode.locked}
                onChange={(event) =>
                  onOperation(
                    updateTextNode(selectedNode, {
                      align: event.target.value as TextAlign
                    })
                  )
                }
              >
                <option value="left">Left</option>
                <option value="center">Center</option>
                <option value="right">Right</option>
                <option value="justify">Justify</option>
              </select>
            </label>
            <NumberField
              label="Line Height"
              value={selectedNode.kind.line_height ?? 1.2}
              min={0.1}
              step={0.05}
              disabled={selectedNode.locked}
              onCommit={(value) => onOperation(updateTextNode(selectedNode, { line_height: value }))}
            />
            <NumberField
              label="Letter Spacing"
              value={selectedNode.kind.letter_spacing ?? 0}
              step={0.25}
              disabled={selectedNode.locked}
              onCommit={(value) => onOperation(updateTextNode(selectedNode, { letter_spacing: value }))}
            />
            <NumberField
              label="Max Lines"
              value={selectedNode.kind.max_lines ?? 0}
              min={0}
              step={1}
              disabled={selectedNode.locked}
              onCommit={(value) =>
                onOperation(updateTextNode(selectedNode, { max_lines: value > 0 ? Math.round(value) : null }))
              }
            />
            <label className="field">
              <span>Wrap</span>
              <select
                value={selectedNode.kind.wrap ?? "wrap"}
                disabled={selectedNode.locked}
                onChange={(event) => onOperation(updateTextNode(selectedNode, { wrap: event.target.value as TextWrap }))}
              >
                <option value="wrap">Wrap</option>
                <option value="no_wrap">No wrap</option>
              </select>
            </label>
            <label className="field">
              <span>Direction</span>
              <select
                value={selectedNode.kind.direction ?? "ltr"}
                disabled={selectedNode.locked}
                onChange={(event) =>
                  onOperation(updateTextNode(selectedNode, { direction: event.target.value as TextDirection }))
                }
              >
                <option value="ltr">LTR</option>
                <option value="rtl">RTL</option>
                <option value="auto">Auto</option>
              </select>
            </label>
            {brandTokens ? (
              <TokenSelect
                label="Style Token"
                value={selectedNode.kind.style_token ?? ""}
                tokens={brandTokens.typography_tokens}
                disabled={selectedNode.locked}
                onChange={(token) => onOperation(updateTextNode(selectedNode, { style_token: token || null }))}
              />
            ) : null}
          </div>
        </section>
  );
}
