"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  imageExportSupportsScale,
  imageExportSupportsTransparency,
  type ImageExportFormat,
  type ImageExportScale,
} from "../model/image-export";

export function useImageExportController({ title }: { title: string }) {
  const [format, setFormat] = useState<ImageExportFormat>("PNG");
  const [menuOpen, setMenuOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [scale, setScale] = useState<ImageExportScale>("1x");
  const [transparentBackground, setTransparentBackground] = useState(true);
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
    const supportsTransparency = imageExportSupportsTransparency(format);
    window.dispatchEvent(new CustomEvent("clue:artifact-export-request", {
      detail: {
        format,
        kind: "ad",
        scale: supportsScale ? scale : undefined,
        title,
        transparentBackground: supportsTransparency ? transparentBackground : false,
      },
    }));
    setStatusMessage(`${format} export requested${supportsScale ? ` at ${scale}` : ""}`);
  }, [format, scale, title, transparentBackground]);

  const chooseFormat = useCallback((nextFormat: ImageExportFormat) => {
    setFormat(nextFormat);
    if (!imageExportSupportsTransparency(nextFormat)) {
      setTransparentBackground(false);
    }
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
      setTransparentBackground,
      statusMessage,
      toggleMenu: () => setMenuOpen((current) => !current),
      transparentBackground,
    },
    menuRef,
  };
}
