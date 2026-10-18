"use client";

import { useState, type ReactNode } from "react";
import type { SiteInspectorBinding } from "@/features/site-editor/model/site-selection";
import { InspectorField, InspectorIcon, InspectorSection, SegmentedControl } from "./inspector-primitives";
import styles from "./chat-shell.module.css";

const MOVES = [
  ["Move up", "layer-up", "up"],
  ["Move down", "layer-down", "down"],
] as const;

/**
 * Arrange (plan 4, spec §4.8): Move up and Move down among the element's neighbours, each one save,
 * shown for any selected element that has neighbours (ruling R6), with a note when its place is fixed
 * (R5). `order`: false for a section's own box (sections do not move here). `children`: a box's content
 * alignment, which belongs in this section too.
 */
export function SiteArrangeSection({ binding, children, order = true }: { binding: SiteInspectorBinding; children?: ReactNode; order?: boolean }) {
  const [open, setOpen] = useState(true);
  const arrange = order ? binding.arrange : null;
  if (!arrange && !children) return null;
  return (
    <InspectorSection label="Arrange" onOpenChange={setOpen} open={open}>
      {arrange ? (
        <InspectorField label="Order">
          {/* The ad editor's Layer row (ad-dummy-inspectors.tsx `DummyIconButtons`), founder 2026-10-19. */}
          <div className={styles.dummyInspectorActionGrid} style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
            {MOVES.map(([label, icon, direction]) => {
              const off = binding.disabled || !(direction === "up" ? arrange.canUp : arrange.canDown);
              return (
                <button aria-label={label} className={off ? styles.inspectorControlDisabled : ""} disabled={off} key={direction} onClick={() => binding.onMove(direction)} type="button">
                  <InspectorIcon name={icon} size={14} />
                </button>
              );
            })}
          </div>
        </InspectorField>
      ) : null}
      {arrange?.note ? (
        <p className={styles.inspectorStatusNote} role="status">
          {arrange.note}
        </p>
      ) : null}
      {children}
    </InspectorSection>
  );
}

/** Hide (plan 4, ruling R9): a header or footer part shown or hidden, one save. */
export function SiteHideSection({ binding }: { binding: SiteInspectorBinding }) {
  const [open, setOpen] = useState(true);
  if (!binding.hide) return null;
  const part = binding.hide.part;
  return (
    <InspectorSection label="Visibility" onOpenChange={setOpen} open={open}>
      <InspectorField label={`In the ${part}`}>
        <SegmentedControl
          ariaLabel={`Show in the ${part}`}
          disabled={binding.disabled}
          onChange={(value) => binding.onHideCommit(value === "hidden")}
          options={[
            { label: "Shown", value: "shown" },
            { label: "Hidden", value: "hidden" },
          ]}
          value={binding.hide.hidden ? "hidden" : "shown"}
        />
      </InspectorField>
    </InspectorSection>
  );
}
