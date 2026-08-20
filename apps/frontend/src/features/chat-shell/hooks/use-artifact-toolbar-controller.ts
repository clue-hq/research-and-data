"use client";

import { useCallback, useEffect, useRef, useState } from "react";
export type ImageEditorTool = "image" | "pointer" | "shape" | "stroke" | "text";
export type ArtifactPreviewDevice = "Desktop" | "Mobile" | "Tablet";

export function useArtifactToolbarController() {
  const [activeTool, setActiveTool] = useState<ImageEditorTool>("pointer");
  const [device, setDevice] = useState<ArtifactPreviewDevice>("Desktop");
  const [deviceMenuOpen, setDeviceMenuOpen] = useState(false);
  // §2.5 interim default: nearest 5% step to the dummy's 23% so the widened
  // menu opens with a checked item; superseded by §1.10 fit-on-open at AD2.8.
  const [zoom, setZoom] = useState("25%");
  const deviceMenuRef = useRef<HTMLDivElement>(null);
  const zoomMenuRef = useRef<HTMLDivElement>(null);
  const [zoomMenuOpen, setZoomMenuOpen] = useState(false);

  const closeMenus = useCallback(() => {
    setDeviceMenuOpen(false);
    setZoomMenuOpen(false);
  }, []);

  useEffect(() => {
    const dismissMenus = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!deviceMenuRef.current?.contains(target)) setDeviceMenuOpen(false);
      if (!zoomMenuRef.current?.contains(target)) setZoomMenuOpen(false);
    };

    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDeviceMenuOpen(false);
        setZoomMenuOpen(false);
      }
    };

    document.addEventListener("pointerdown", dismissMenus);
    document.addEventListener("keydown", dismissOnEscape);
    return () => {
      document.removeEventListener("pointerdown", dismissMenus);
      document.removeEventListener("keydown", dismissOnEscape);
    };
  }, []);

  const chooseDevice = useCallback((nextDevice: ArtifactPreviewDevice) => {
    setDevice(nextDevice);
    setDeviceMenuOpen(false);
  }, []);

  const chooseZoom = useCallback((nextZoom: string) => {
    setZoom(nextZoom);
    setZoomMenuOpen(false);
  }, []);

  const toggleDeviceMenu = useCallback(() => {
    setZoomMenuOpen(false);
    setDeviceMenuOpen((current) => !current);
  }, []);

  const toggleZoomMenu = useCallback(() => {
    setDeviceMenuOpen(false);
    setZoomMenuOpen((current) => !current);
  }, []);

  return {
    activeTool,
    chooseDevice,
    chooseZoom,
    closeMenus,
    device,
    deviceMenuOpen,
    deviceMenuRef,
    setActiveTool,
    toggleDeviceMenu,
    toggleZoomMenu,
    zoom,
    zoomMenuOpen,
    zoomMenuRef,
  };
}
