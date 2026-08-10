"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type SidebarState =
  | "collapsed"
  | "hover-preview"
  | "pinned-expanded";

export type SidebarStateEvent = "preview" | "toggle" | "dismiss";

export const SIDEBAR_PREVIEW_DISMISS_MS = 140;
export const PROJECT_SIDEBAR_TRIGGER_ID = "project-sidebar-toggle";

/** The executable desktop state table from the ratified R6 contract. */
export function nextSidebarState(
  state: SidebarState,
  event: SidebarStateEvent,
): SidebarState {
  if (event === "preview") {
    return state === "collapsed" ? "hover-preview" : state;
  }
  if (event === "dismiss") {
    return state === "hover-preview" ? "collapsed" : state;
  }
  return state === "pinned-expanded" ? "collapsed" : "pinned-expanded";
}

function restoreFocus(element: HTMLButtonElement | null) {
  requestAnimationFrame(() => {
    const target =
      element ?? document.getElementById(PROJECT_SIDEBAR_TRIGGER_ID);
    if (target instanceof HTMLButtonElement) target.focus();
  });
}

export function useDesktopSidebar(initialState: SidebarState) {
  const [state, setState] = useState<SidebarState>(initialState);
  const dismissal = useRef<ReturnType<typeof setTimeout> | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);

  const cancelDismissal = useCallback(() => {
    if (dismissal.current === null) return;
    clearTimeout(dismissal.current);
    dismissal.current = null;
  }, []);

  const preview = useCallback(
    (element?: HTMLButtonElement) => {
      cancelDismissal();
      if (element) trigger.current = element;
      setState((current) => nextSidebarState(current, "preview"));
    },
    [cancelDismissal],
  );

  const scheduleDismissal = useCallback(() => {
    cancelDismissal();
    dismissal.current = setTimeout(() => {
      dismissal.current = null;
      setState((current) => nextSidebarState(current, "dismiss"));
    }, SIDEBAR_PREVIEW_DISMISS_MS);
  }, [cancelDismissal]);

  const toggle = useCallback(
    (element?: HTMLButtonElement) => {
      cancelDismissal();
      if (element) trigger.current = element;
      const closes = state === "pinned-expanded";
      setState((current) => nextSidebarState(current, "toggle"));
      if (closes) restoreFocus(element ?? trigger.current);
    },
    [cancelDismissal, state],
  );

  const closeFromSidebar = useCallback(() => {
    cancelDismissal();
    setState("collapsed");
    restoreFocus(trigger.current);
  }, [cancelDismissal]);

  useEffect(() => cancelDismissal, [cancelDismissal]);

  useEffect(() => {
    if (state !== "hover-preview") return;
    function handleEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeFromSidebar();
    }
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [closeFromSidebar, state]);

  return {
    cancelDismissal,
    closeFromSidebar,
    expanded: state !== "collapsed",
    preview,
    scheduleDismissal,
    state,
    toggle,
  };
}

export type DesktopSidebarController = ReturnType<typeof useDesktopSidebar>;
