"use client";

import { useState, type ReactNode } from "react";
import type { SiteInspectorBinding } from "@/features/site-editor/model/site-selection";
import { InspectorField, InspectorSection, SegmentedControl } from "./inspector-primitives";
import styles from "./chat-shell.module.css";

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
          <div className={styles.fieldGrid}>
            <button className={styles.inspectorControl} disabled={binding.disabled || !arrange.canUp} onClick={() => binding.onMove("up")} type="button">
              ↑ Move up
            </button>
            <button className={styles.inspectorControl} disabled={binding.disabled || !arrange.canDown} onClick={() => binding.onMove("down")} type="button">
              ↓ Move down
            </button>
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
