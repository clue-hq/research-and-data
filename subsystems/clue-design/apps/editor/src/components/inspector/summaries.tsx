"use client";

import type { Diagnostic, Page } from "@/engine/contracts";
import type { SelectionChromeModel } from "@/engine/selectionChrome";
import { countDiagnostics, diagnosticCountLabel } from "./diagnostics";

/** Read-only selection summaries shown at the top of the inspector. */

export function SelectedArtboardSummary({ activePage, diagnostics }: { activePage: Page; diagnostics: Diagnostic[] }) {
  const counts = countDiagnostics(diagnostics);
  return (
    <div className="selection-summary" aria-label="Selected artboard summary">
      <div>
        <span>Artboard</span>
        <strong>{activePage.name}</strong>
      </div>
      <div>
        <span>Size</span>
        <strong>
          {formatDimension(activePage.size.width)} x {formatDimension(activePage.size.height)} {activePage.size.unit}
        </strong>
      </div>
      <div>
        <span>Issues</span>
        <strong>{diagnosticCountLabel(counts)}</strong>
      </div>
    </div>
  );
}

export function SelectedObjectSummary({
  model,
  locked,
  layoutManaged,
  pinned = false
}: {
  model: SelectionChromeModel;
  locked: boolean;
  layoutManaged: boolean;
  pinned?: boolean;
}) {
  const objectKind =
    model.isSlotBound && model.baseObjectKind
      ? `slot-bound ${objectKindLabel(model.baseObjectKind)}`
      : model.baseObjectKind
        ? objectKindLabel(model.baseObjectKind)
        : "unknown";
  return (
    <div className="selection-summary" aria-label="Selected object summary">
      <div>
        <span>Object</span>
        <strong>{objectKind}</strong>
      </div>
      <div>
        <span>Canvas handles</span>
        <strong>{model.showHandles ? "Enabled" : "Disabled"}</strong>
      </div>
      <div>
        <span>State</span>
        <strong>{selectionStateLabel({ locked, layoutManaged, pinned, isSlotBound: model.isSlotBound })}</strong>
      </div>
      <div>
        <span>Slots</span>
        <strong>{model.slotKeys.length > 0 ? model.slotKeys.join(", ") : "Static"}</strong>
      </div>
      <div>
        <span>Issues</span>
        <strong>{diagnosticCountLabel(model.diagnosticCounts)}</strong>
      </div>
    </div>
  );
}

function selectionStateLabel({
  locked,
  layoutManaged,
  pinned = false,
  isSlotBound
}: {
  locked: boolean;
  layoutManaged: boolean;
  pinned?: boolean;
  isSlotBound: boolean;
}): string {
  const states = [
    locked ? "Locked" : null,
    pinned ? "Pinned (freehand)" : layoutManaged ? "Layout-managed child" : null,
    isSlotBound ? "Slot-bound" : null
  ].filter((state): state is string => Boolean(state));
  return states.length > 0 ? states.join(" / ") : "Editable";
}

function objectKindLabel(kind: string): string {
  return kind.replace(/_/g, " ");
}

function formatDimension(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(/\.0$/, "");
}
