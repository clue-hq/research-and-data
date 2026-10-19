"use client";

import { useRef, type ReactNode } from "react";
import styles from "./chat-shell.module.css";
import { useLayerListFill } from "./use-layer-list-fill";

/** The inspector's Layers list: rows at their full height, scrolling inside a box that fills the panel
 * down to its bottom or to the chat box (founder 2026-10-19). Shared by the site and scene-ad inspectors;
 * the measuring ref lives here, so a schema file holds no ref of its own (ruling L20, AD4.R). */
export function LayerList({ children }: { children: ReactNode }) {
  const listRef = useRef<HTMLDivElement>(null);
  useLayerListFill(listRef);
  return (
    <div className={styles.layerList} ref={listRef}>
      {children}
    </div>
  );
}
