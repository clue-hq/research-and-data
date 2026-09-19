"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  imageExportSupportsScale,
  type ImageExportFormat,
  type ImageExportScale,
} from "../model/image-export";

/**
 * Artifacts page (2026-09-15): `onExport` is the ADDITIVE direct leg. The
 * editor's callers pass none and keep the original event-dispatch path
 * untouched — there the window listener (`use-scene-export.ts`) owns the
 * export and its status. A caller that has no such listener on the page (the
 * artifacts gallery) passes `onExport` and the menu awaits it directly,
 * announcing what actually happened rather than what was requested.
 */
export function useImageExportController({
  title,
  onExport,
}: {
  title: string;
  onExport?: (options: { format: ImageExportFormat; scale: ImageExportScale }) => Promise<void>;
}) {
  const [format, setFormat] = useState<ImageExportFormat>("PNG");
  const [menuOpen, setMenuOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [scale, setScale] = useState<ImageExportScale>("1x");
  const [statusMessage, setStatusMessage] = useState("");
  const [exporting, setExporting] = useState(false);
  /**
   * Whether the LAST direct-leg attempt ended with no file. It exists so a
   * caller can hand `ImageExportMenu` a `SceneExportStatus` and get a refusal
   * rendered VISIBLY — the menu promotes its status line out of the `.srOnly`
   * span only on `failed` (`image-export-menu.tsx`), and without this a direct
   * -leg refusal was announced to screen readers alone, which is the exact
   * defect `SceneExportStatus.failed` was introduced to prevent.
   *
   * The event-dispatch path never touches it: there the window listener owns
   * the outcome and supplies its own status, so the editor is unchanged.
   */
  const [exportFailed, setExportFailed] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const closeMenu = useCallback(() => setMenuOpen(false), []);

  useEffect(() => {
    const dismissOnPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) closeMenu();
    };
    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeMenu();
    };
    document.addEventListener("pointerdown", dismissOnPointerDown);
    document.addEventListener("keydown", dismissOnEscape);
    return () => {
      document.removeEventListener("pointerdown", dismissOnPointerDown);
      document.removeEventListener("keydown", dismissOnEscape);
    };
  }, [closeMenu]);

  const requestExport = useCallback(async () => {
    if (onExport) {
      // Single-flight: a second click while a 4x PNG is still rendering would
      // start a second identical export and land two files.
      if (exporting) return;
      setExporting(true);
      setStatusMessage("");
      setExportFailed(false);
      try {
        await onExport({ format, scale });
        setStatusMessage(`${format} download started`);
        setExportFailed(false);
      } catch (error) {
        setStatusMessage(error instanceof Error ? error.message : "Export failed. Please try again.");
        setExportFailed(true);
      } finally {
        setExporting(false);
      }
      return;
    }
    const supportsScale = imageExportSupportsScale(format);
    // Gate G-E: the request detail carries no `transparentBackground` field —
    // the toggle is held pending the §8 engine verification.
    window.dispatchEvent(new CustomEvent("clue:artifact-export-request", {
      detail: {
        format,
        kind: "ad",
        scale: supportsScale ? scale : undefined,
        title,
      },
    }));
    setStatusMessage(`${format} export requested${supportsScale ? ` at ${scale}` : ""}`);
  }, [exporting, format, onExport, scale, title]);

  const chooseFormat = useCallback((nextFormat: ImageExportFormat) => {
    setFormat(nextFormat);
  }, []);

  return {
    controller: {
      closeMenu,
      exportFailed,
      exporting,
      format,
      menuOpen,
      previewOpen,
      requestExport,
      scale,
      setFormat: chooseFormat,
      setPreviewOpen,
      setScale,
      statusMessage,
      toggleMenu: () => setMenuOpen((current) => !current),
    },
    menuRef,
  };
}
