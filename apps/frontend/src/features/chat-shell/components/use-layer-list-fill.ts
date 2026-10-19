"use client";

import { useLayoutEffect, type RefObject } from "react";
import { layerListHeight } from "@/features/site-editor/model/site-layers";
import styles from "./chat-shell.module.css";

/**
 * Layers fills the inspector down to the bottom of its scrolling dock, or to the chat box's top when it
 * is open (the dock already ends there), however few rows it has; with too little room it keeps a
 * minimum and the dock scrolls (founder 2026-10-19). Measured, because the section around the list sizes
 * itself to its content for its open and close animation. Used by the site and the scene-ad inspectors.
 */
export function useLayerListFill(listRef: RefObject<HTMLDivElement | null>) {
  useLayoutEffect(() => {
    const list = listRef.current;
    const dock = list?.closest<HTMLElement>(`.${styles.inspectorDock}`);
    if (!list || !dock) return;
    const fit = () => {
      const listTop = list.getBoundingClientRect().top - dock.getBoundingClientRect().top + dock.scrollTop;
      const section = list.closest("section");
      const bottomGap = section ? section.getBoundingClientRect().bottom - list.getBoundingClientRect().bottom : undefined;
      // The list IS that height (not capped at it), so Layers reaches the bottom however few rows it has.
      list.style.height = `${layerListHeight({ dockHeight: dock.clientHeight, listTop, bottomGap })}px`;
      list.style.maxHeight = "none";
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(dock);
    // The rail is the panel's content (the aside always fills the dock, so it never reports a change):
    // it changes height whenever a section above opens, closes or changes.
    const rail = list.closest<HTMLElement>(`.${styles.inspectorRail}`);
    if (rail) observer.observe(rail);
    return () => observer.disconnect();
  }, [listRef]);
}
