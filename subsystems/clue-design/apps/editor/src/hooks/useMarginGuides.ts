import { useState } from "react";

/**
 * View preference (not per-document) for rendering the active page's
 * safe-area and bleed guides on the canvas. Defaults off, persisted to
 * localStorage so the toggle survives a reload without needing a document.
 */
const STORAGE_KEY = "lumen.editor.show-margin-guides";

function readStored(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return window.localStorage.getItem(STORAGE_KEY) === "true";
}

function writeStored(value: boolean): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, value ? "true" : "false");
}

export function useMarginGuides() {
  const [showMarginGuides, setShowMarginGuides] = useState(readStored);

  const toggleMarginGuides = () => {
    setShowMarginGuides((current) => {
      const next = !current;
      writeStored(next);
      return next;
    });
  };

  return { showMarginGuides, toggleMarginGuides };
}
