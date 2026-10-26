"use client";

import { useSyncExternalStore } from "react";

/**
 * Whether this tab is showing (`document.visibilityState === "visible"`).
 *
 * The chat holds its thread stream only while the tab is visible (CRM trial 1,
 * F2, option (a)): a hidden tab closes it and reopens it from its cursor when
 * shown again. Rendered on the server, the tab counts as not visible, so no
 * stream is opened before the page is in a browser.
 */
export function usePageVisible(): boolean {
  return useSyncExternalStore(subscribe, isVisible, () => false);
}

function subscribe(onChange: () => void): () => void {
  document.addEventListener("visibilitychange", onChange);
  return () => document.removeEventListener("visibilitychange", onChange);
}

function isVisible(): boolean {
  return document.visibilityState === "visible";
}
