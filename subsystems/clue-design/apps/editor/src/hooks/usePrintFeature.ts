import { useState } from "react";

/**
 * Master view-preference toggle for the "Print & bleed" feature (print
 * workstream W3). Mirrors the `useMarginGuides` idiom exactly: a boolean
 * persisted to localStorage so the choice survives a reload without needing a
 * document. Defaults OFF (product decision D6) — with it off, every print
 * affordance (trim guide, bleed-extent clip, print presets, the bleed/marks
 * export controls, the print-ready report) is hidden/inert and the editor
 * behaves exactly as today.
 */
const STORAGE_KEY = "lumen.editor.print-and-bleed";

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

export function usePrintFeature() {
  const [printFeatureEnabled, setPrintFeatureEnabled] = useState(readStored);

  const togglePrintFeature = () => {
    setPrintFeatureEnabled((current) => {
      const next = !current;
      writeStored(next);
      return next;
    });
  };

  return { printFeatureEnabled, togglePrintFeature };
}
