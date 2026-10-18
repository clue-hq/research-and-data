"use client";

import { useState } from "react";
import type { SiteInspectorBinding } from "@/features/site-editor/model/site-selection";
import { InspectorSection } from "./inspector-primitives";
import styles from "./chat-shell.module.css";

export const HEADER_OVERLAY_NOTE = "The first section now starts under the header. If its words sit under the header, give it more top padding.";

/** Plan 6 (rulings R10, R12): the header's own placement, shown when the header itself is selected:
 * it stays at the top while the page scrolls, and/or sits over the first section. Each change is one save. */
export function SiteHeaderPlacement({ binding }: { binding: SiteInspectorBinding }) {
  const [open, setOpen] = useState(true);
  const placement = binding.headerPlacement;
  if (!placement) return null;
  return (
    <InspectorSection label="Header" onOpenChange={setOpen} open={open}>
      {/* Founder 2026-10-19: checkboxes, checked when on. */}
      <label className={styles.checkboxRow}>
        <input checked={placement.sticky} disabled={binding.disabled} onChange={(event) => binding.onHeaderPlacementCommit("sticky", event.target.checked)} type="checkbox" />
        <span>Stays at the top while scrolling</span>
      </label>
      <label className={styles.checkboxRow}>
        <input checked={placement.overlay} disabled={binding.disabled} onChange={(event) => binding.onHeaderPlacementCommit("overlay", event.target.checked)} type="checkbox" />
        <span>Sits over the first section</span>
      </label>
      {placement.overlay ? (
        <p className={styles.inspectorStatusNote} role="status">
          {HEADER_OVERLAY_NOTE}
        </p>
      ) : null}
    </InspectorSection>
  );
}
