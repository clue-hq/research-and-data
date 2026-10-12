"use client";

import { FileIcon, HouseIcon, SearchIcon } from "lucide-react";
import { useState } from "react";
import { filterPageRows, type SitePageRow } from "@/features/site-editor/model/site-pages";
import { InspectorInput } from "./inspector-primitives";
import styles from "./chat-shell.module.css";

/**
 * DESIGN REVIEW (DR2): the page panel (founder ruling 2026-10-11, the Ploy reference): a count, a
 * search box, one row per page with a home icon for "/". Adding, renaming and deleting pages stays
 * with the agent until those controls are designed.
 */
export function SitePagesPanel({ onOpen, rows }: { onOpen: (route: string) => void; rows: readonly SitePageRow[] }) {
  const [query, setQuery] = useState("");
  const shown = filterPageRows(rows, query);
  return (
    <nav aria-label="Pages" className={styles.sitePagesPanel}>
      <div className={styles.sitePagesPanelHead}>
        <span className={styles.inspectorFieldLabel}>{`Pages ${rows.length}`}</span>
        <InspectorInput
          ariaLabel="Search pages"
          leading={<SearchIcon absoluteStrokeWidth aria-hidden="true" size={14} strokeWidth={1.25} />}
          onChange={setQuery}
          placeholder="Search pages…"
          value={query}
        />
      </div>
      <div className={styles.sitePagesPanelList}>
        {shown.map((row) => {
          const Icon = row.home ? HouseIcon : FileIcon;
          return (
            <button
              aria-current={row.active ? "page" : undefined}
              className={`${styles.layerRow} ${row.active ? styles.layerRowActive : ""}`}
              key={row.route}
              onClick={() => onOpen(row.route)}
              title={row.route}
              type="button"
            >
              <span className={styles.layerRowContent}>
                <span className={styles.layerRowLabel}>
                  <Icon absoluteStrokeWidth aria-hidden="true" size={16} strokeWidth={1.25} />
                  <span className={styles.layerRowLabelText}>{row.title}</span>
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
