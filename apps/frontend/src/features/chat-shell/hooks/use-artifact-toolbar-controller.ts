"use client";

import { useCallback, useEffect, useRef, useState } from "react";
export type ImageEditorTool = "image" | "pointer" | "shape" | "stroke" | "text";
export type ArtifactPreviewDevice = "Desktop" | "Mobile" | "Tablet";

export function useArtifactToolbarController({
  device: controlledDevice,
  onDeviceChange,
  onZoomChange,
  zoom: controlledZoom,
}: {
  /** The device to display. Present → controlled (the artifact stage owns the
   * value, because it also drives the web canvas viewport width); absent → the
   * local fallback below. Same lift as `zoom`/`onZoomChange`. */
  device?: ArtifactPreviewDevice | null;
  /** Present → a device choice is REPORTED, never stored here; the caller
   * feeds it back through `device`, so the menu and the stage viewport can
   * never disagree. */
  onDeviceChange?: (device: ArtifactPreviewDevice) => void;
  /** AD2.8: present → a menu choice is REPORTED, never stored here; the caller
   * (the ad editing session) owns the value and feeds it back through `zoom`,
   * so the menu and the canvas viewport can never disagree. */
  onZoomChange?: (zoom: string) => void;
  /** AD2.8: the zoom to display. Present → controlled; absent → the local
   * fallback below. */
  zoom?: string | null;
} = {}) {
  const [activeTool, setActiveTool] = useState<ImageEditorTool>("pointer");
  const [uncontrolledDevice, setUncontrolledDevice] =
    useState<ArtifactPreviewDevice>("Desktop");
  const device = controlledDevice ?? uncontrolledDevice;
  const [deviceMenuOpen, setDeviceMenuOpen] = useState(false);
  // §2.5 interim default: nearest 5% step to the dummy's 23% so the widened
  // menu opens with a checked item. AD2.8 supersedes it wherever a real canvas
  // is mounted (the session passes fit-on-open in); it survives only as the
  // uncontrolled fallback for a header with no scene behind it.
  const [uncontrolledZoom, setUncontrolledZoom] = useState("25%");
  const zoom = controlledZoom ?? uncontrolledZoom;
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

  const chooseDevice = useCallback(
    (nextDevice: ArtifactPreviewDevice) => {
      if (onDeviceChange) {
        onDeviceChange(nextDevice);
      } else {
        setUncontrolledDevice(nextDevice);
      }
      setDeviceMenuOpen(false);
    },
    [onDeviceChange],
  );

  const chooseZoom = useCallback(
    (nextZoom: string) => {
      if (onZoomChange) {
        onZoomChange(nextZoom);
      } else {
        setUncontrolledZoom(nextZoom);
      }
      setZoomMenuOpen(false);
    },
    [onZoomChange],
  );

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
