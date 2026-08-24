"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  imageExportSupportsScale,
  type ImageExportFormat,
  type ImageExportScale,
} from "../model/image-export";

export function useImageExportController({ title }: { title: string }) {
  const [format, setFormat] = useState<ImageExportFormat>("PNG");
  const [menuOpen, setMenuOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [scale, setScale] = useState<ImageExportScale>("1x");
  const [statusMessage, setStatusMessage] = useState("");
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

  const requestExport = useCallback(() => {
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
  }, [format, scale, title]);

  const chooseFormat = useCallback((nextFormat: ImageExportFormat) => {
    setFormat(nextFormat);
  }, []);

  return {
    controller: {
      closeMenu,
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
