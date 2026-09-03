"use client";

import { useCallback, useEffect, useRef, useState } from "react";
export type ImageEditorTool = "image" | "pointer" | "shape" | "stroke" | "text";
export type ArtifactPreviewDevice = "Desktop" | "Mobile" | "Tablet";

/** F5 task 18: one page of the active multi-page web document, as the header's
 * menu needs it. Structurally the web editing session's own page summary — the
 * presentation side names its own prop shape rather than importing the
 * design-editor document type. */
export interface ArtifactPageOption {
  id: string;
  name: string;
  route: string;
}

/**
 * The toolbar's menus are all LIFTED the same way: when the caller passes a
 * change handler the choice is REPORTED and never stored here (the caller owns
 * the value and hands it back, so the menu and the surface it drives can never
 * disagree); with no handler the local fallback stores it. One dispatcher so
 * device, zoom and page cannot drift apart.
 */
export function applyLiftedChoice<T>(
  next: T,
  report: ((value: T) => void) | undefined,
  store: (value: T) => void,
): void {
  if (report) {
    report(next);
  } else {
    store(next);
  }
}

export function useArtifactToolbarController({
  activePageId: controlledPageId,
  device: controlledDevice,
  onDeviceChange,
  onPageChange,
  onZoomChange,
  pages,
  zoom: controlledZoom,
}: {
  /** F5 task 18: the page to display. Present → controlled (the web editing
   * session owns it, because the same value drives the canvas render);
   * absent → the local fallback below. Same lift as `device`/`zoom`. */
  activePageId?: string | null;
  /** The device to display. Present → controlled (the artifact stage owns the
   * value, because it also drives the web canvas viewport width); absent → the
   * local fallback below. Same lift as `zoom`/`onZoomChange`. */
  device?: ArtifactPreviewDevice | null;
  /** Present → a device choice is REPORTED, never stored here; the caller
   * feeds it back through `device`, so the menu and the stage viewport can
   * never disagree. */
  onDeviceChange?: (device: ArtifactPreviewDevice) => void;
  /** F5 task 18: present → a page choice is REPORTED, never stored here; the
   * caller (the web editing session) owns the value and feeds it back through
   * `activePageId`, so the menu and the rendered page can never disagree. */
  onPageChange?: (pageId: string) => void;
  /** F5 task 18: the active document's pages. Empty/absent → no page menu. */
  pages?: readonly ArtifactPageOption[];
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
  // F5 task 18: the page menu's own local fallback, for a header mounted with
  // no session behind it. Derived (never reset in an effect): a stored id the
  // current page list no longer has falls back to the first page.
  const [uncontrolledPageId, setUncontrolledPageId] = useState<string | null>(null);
  const requestedPageId = controlledPageId ?? uncontrolledPageId;
  const activePageId =
    pages?.find((page) => page.id === requestedPageId)?.id ??
    pages?.[0]?.id ??
    null;
  const activePage = pages?.find((page) => page.id === activePageId) ?? null;
  const [pageMenuOpen, setPageMenuOpen] = useState(false);
  const pageMenuRef = useRef<HTMLDivElement>(null);
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
    setPageMenuOpen(false);
    setZoomMenuOpen(false);
  }, []);

  useEffect(() => {
    const dismissMenus = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!deviceMenuRef.current?.contains(target)) setDeviceMenuOpen(false);
      if (!pageMenuRef.current?.contains(target)) setPageMenuOpen(false);
      if (!zoomMenuRef.current?.contains(target)) setZoomMenuOpen(false);
    };

    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDeviceMenuOpen(false);
        setPageMenuOpen(false);
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
      applyLiftedChoice(nextDevice, onDeviceChange, setUncontrolledDevice);
      setDeviceMenuOpen(false);
    },
    [onDeviceChange],
  );

  const choosePage = useCallback(
    (nextPageId: string) => {
      applyLiftedChoice(nextPageId, onPageChange, setUncontrolledPageId);
      setPageMenuOpen(false);
    },
    [onPageChange],
  );

  const chooseZoom = useCallback(
    (nextZoom: string) => {
      applyLiftedChoice(nextZoom, onZoomChange, setUncontrolledZoom);
      setZoomMenuOpen(false);
    },
    [onZoomChange],
  );

  const toggleDeviceMenu = useCallback(() => {
    setPageMenuOpen(false);
    setZoomMenuOpen(false);
    setDeviceMenuOpen((current) => !current);
  }, []);

  const togglePageMenu = useCallback(() => {
    setDeviceMenuOpen(false);
    setZoomMenuOpen(false);
    setPageMenuOpen((current) => !current);
  }, []);

  const toggleZoomMenu = useCallback(() => {
    setDeviceMenuOpen(false);
    setPageMenuOpen(false);
    setZoomMenuOpen((current) => !current);
  }, []);

  return {
    activePage,
    activePageId,
    activeTool,
    chooseDevice,
    choosePage,
    chooseZoom,
    closeMenus,
    device,
    deviceMenuOpen,
    deviceMenuRef,
    pageMenuOpen,
    pageMenuRef,
    setActiveTool,
    toggleDeviceMenu,
    togglePageMenu,
    toggleZoomMenu,
    zoom,
    zoomMenuOpen,
    zoomMenuRef,
  };
}
