"use client";

import { useState } from "react";
import type { SiteInspectorBinding } from "@/features/site-editor/model/site-selection";
import { InspectorField, InspectorSection, SegmentedControl } from "./inspector-primitives";
import styles from "./chat-shell.module.css";

export const HEADER_OVERLAY_NOTE = "The first section now starts under the header. If its words sit under the header, give it more top padding.";

const ON_OFF = [
  { label: "Off", value: "off" },
  { label: "On", value: "on" },
];

/** Plan 6 (rulings R10, R12): the header's own placement, shown when the header itself is selected:
 * it stays at the top while the page scrolls, and/or sits over the first section. Each change is one save. */
export function SiteHeaderPlacement({ binding }: { binding: SiteInspectorBinding }) {
  const [open, setOpen] = useState(true);
  const placement = binding.headerPlacement;
  if (!placement) return null;
  return (
    <InspectorSection label="Header" onOpenChange={setOpen} open={open}>
      <InspectorField label="Stays at the top while scrolling">
        <SegmentedControl
          ariaLabel="Stays at the top while scrolling"
          disabled={binding.disabled}
          onChange={(value) => binding.onHeaderPlacementCommit("sticky", value === "on")}
          options={ON_OFF}
          value={placement.sticky ? "on" : "off"}
        />
      </InspectorField>
      <InspectorField label="Sits over the first section">
        <SegmentedControl
          ariaLabel="Sits over the first section"
          disabled={binding.disabled}
          onChange={(value) => binding.onHeaderPlacementCommit("overlay", value === "on")}
          options={ON_OFF}
          value={placement.overlay ? "on" : "off"}
        />
      </InspectorField>
      {placement.overlay ? (
        <p className={styles.inspectorStatusNote} role="status">
          {HEADER_OVERLAY_NOTE}
        </p>
      ) : null}
    </InspectorSection>
  );
}
