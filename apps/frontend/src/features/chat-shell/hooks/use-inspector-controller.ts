"use client";

import { useCallback, useState } from "react";
import type { ChatShellInspectorSelection } from "../model/chat-shell";

export type InspectorSectionId =
  | "arrange"
  | "alignment"
  | "background"
  | "dimensions"
  | "fill"
  | "layers"
  | "layout"
  | "link"
  | "icon"
  | "shape"
  | "style"
  | "stroke"
  | "typography";

export type HorizontalAlignment = "center" | "left" | "right";
export type VerticalAlignment = "bottom" | "middle" | "top";
export type InspectorDirection = "horizontal" | "vertical";
export type InspectorLayoutMode = "Flex" | "Grid" | "Hide";
export type InspectorFillType = "linear-gradient" | "radial-gradient" | "solid";

export interface InspectorGradientStop {
  color: string;
  position: number;
}

export interface InspectorBackgroundFill {
  angle: number;
  stops: InspectorGradientStop[];
  type: InspectorFillType;
}

export interface InspectorPresentationState {
  backgroundColor: string;
  backgroundFill: InspectorBackgroundFill;
  buttonLabel: string;
  direction: InspectorDirection;
  fillMode: string;
  fontFamily: string;
  fontSize: string;
  fontWeight: string;
  horizontalAlignment: HorizontalAlignment;
  iconName: string;
  iconSize: string;
  iconStroke: string;
  /** W4.2 §1 row 12 (ruling R-B5): the Fill section's preview image. Defaults
   * to the dummy's stock png; a hydrated image node points it at its own
   * asset's bytes. */
  imagePreviewSrc: string;
  layoutMode: InspectorLayoutMode;
  locked: boolean;
  openInNewTab: boolean;
  openSections: Record<InspectorSectionId, boolean>;
  padding: Record<"bottom" | "left" | "right" | "top", string>;
  position: Record<"x" | "y", string>;
  radius: Record<"all" | "bottomLeft" | "bottomRight" | "topLeft" | "topRight", string>;
  rotation: string;
  sizePreset: string;
  strokeColor: string;
  strokeWidth: string;
  textColor: string;
  /** W3.2 §2 addition (ruling 25): the text style/variant select. */
  textStyle: string;
  /** W3.2 §2 addition (ruling 26): the line-spacing select. */
  lineSpacing: string;
  tokenBackgroundColor: string;
  tokenTextColor: string;
  url: string;
  verticalAlignment: VerticalAlignment;
  visible: boolean;
  gap: string;
  wrap: boolean;
}

const DEFAULT_OPEN_SECTIONS: Record<InspectorSectionId, boolean> = {
  arrange: false,
  alignment: true,
  background: true,
  dimensions: true,
  fill: true,
  layers: true,
  layout: false,
  link: true,
  icon: true,
  shape: true,
  style: true,
  stroke: false,
  typography: true,
};

const DEFAULT_STATE: InspectorPresentationState = {
  backgroundColor: "#00F59B",
  backgroundFill: {
    angle: 0,
    stops: [
      { color: "#163173", position: 0 },
      { color: "#0E1E47", position: 50 },
      { color: "#091530", position: 75 },
      { color: "#050B1A", position: 100 },
    ],
    type: "radial-gradient",
  },
  buttonLabel: "Primary",
  direction: "horizontal",
  fillMode: "Fit",
  fontFamily: "Inter",
  fontSize: "24",
  fontWeight: "Semi Bold",
  horizontalAlignment: "left",
  iconName: "Apple",
  iconSize: "Large",
  iconStroke: "Default",
  imagePreviewSrc: "/icons/chat-shell/inspector/web/image-preview.png",
  layoutMode: "Flex",
  locked: false,
  openInNewTab: false,
  openSections: DEFAULT_OPEN_SECTIONS,
  padding: { bottom: "4", left: "8", right: "8", top: "4" },
  position: { x: "123", y: "4354" },
  radius: { all: "0", bottomLeft: "4", bottomRight: "4", topLeft: "4", topRight: "4" },
  rotation: "0",
  sizePreset: "Linkedin square (1:1) - 1024x1024",
  strokeColor: "none",
  strokeWidth: "1",
  textColor: "#00F59B",
  textStyle: "Body",
  lineSpacing: "normal",
  tokenBackgroundColor: "White",
  tokenTextColor: "Content",
  url: "",
  verticalAlignment: "top",
  visible: true,
  gap: "0",
  wrap: true,
};

/**
 * W3.1 (the contract-doc amendment, additive): every inspector event detail
 * carries write addressing — WHICH node (`selectionId`), WHICH artifact
 * (`artifactId`), and the document version the values were hydrated from
 * (`documentVersion`, the optimistic-concurrency `base_version` W3.2's write
 * adapter sends). Presentation components pass through what the controller
 * holds; nulls mean "not addressable" (no real selection/document) and the
 * write adapter must ignore such events.
 */
export interface InspectorEventAddressing {
  artifactId: string | null;
  documentVersion: number | null;
  selectionId: string | null;
}

/** Exported for the addressing unit test; production callers go through the
 * controller hooks. */
export function dispatchInspectorEvent(
  name: string,
  detail: Record<string, unknown>,
  addressing?: InspectorEventAddressing,
) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent(name, { detail: { ...detail, ...addressing } }),
  );
}

export function useInspectorController(
  collapsedSections: InspectorSectionId[] = [],
  selectionType: ChatShellInspectorSelection = "canvas",
  // W2.2: the hydration seam — real values from the selected node (the
  // design-editor hydrate adapter) merge over the dummy defaults at mount.
  // Initial state only, by design: callers remount the inspector per
  // selection (keyed on the selected node), exactly how the dummy swaps
  // schema views, so a new selection re-hydrates naturally.
  hydrated?: Partial<InspectorPresentationState>,
  // W3.1: write addressing stamped onto every dispatched event detail.
  addressing?: InspectorEventAddressing,
) {
  const [state, setState] = useState<InspectorPresentationState>(() => ({
      ...DEFAULT_STATE,
      ...hydrated,
      openSections: {
      ...DEFAULT_OPEN_SECTIONS,
      ...Object.fromEntries(collapsedSections.map((section) => [section, false])),
      ...hydrated?.openSections,
    },
  }));

  const setValue = useCallback(
    <Key extends keyof InspectorPresentationState>(
      key: Key,
      value: InspectorPresentationState[Key],
    ) => {
      setState((current) => ({ ...current, [key]: value }));
      dispatchInspectorEvent(
        "clue:inspector-property-change",
        {
          property: key,
          selectionType,
          value,
        },
        addressing,
      );
    },
    [addressing, selectionType],
  );

  const setNestedValue = useCallback(
    <Key extends "padding" | "position" | "radius">(
      key: Key,
      nestedKey: keyof InspectorPresentationState[Key],
      value: string,
    ) => {
      setState((current) => ({
        ...current,
        [key]: { ...current[key], [nestedKey]: value },
      }));
      dispatchInspectorEvent(
        "clue:inspector-property-change",
        {
          property: `${key}.${String(nestedKey)}`,
          selectionType,
          value,
        },
        addressing,
      );
    },
    [addressing, selectionType],
  );

  // W3.2 (R3): the two-axis padding path — one committed axis value updates
  // both sides and dispatches a single `padding.x`/`padding.y` event (the
  // write adapter's vocabulary). Used by the axis-collapsed padding boxes.
  const setPaddingAxis = useCallback(
    (axis: "x" | "y", value: string) => {
      setState((current) => ({
        ...current,
        padding:
          axis === "x"
            ? { ...current.padding, left: value, right: value }
            : { ...current.padding, bottom: value, top: value },
      }));
      dispatchInspectorEvent(
        "clue:inspector-property-change",
        {
          property: `padding.${axis}`,
          selectionType,
          value,
        },
        addressing,
      );
    },
    [addressing, selectionType],
  );

  // W4.2 (founder ruling F2, 2026-08-18): the all-corners radius commit. ONE
  // `radius.all` event — the write path's F2 chain clears the four per-corner
  // overrides inside the same operation, so when it does (`clearCorners`) the
  // corner fields mirror that here rather than keep showing overrides the
  // document no longer carries. Dispatching four corner events instead would
  // also lose three of them to the one-in-flight write discipline.
  const setRadiusAll = useCallback(
    (value: string, clearCorners: boolean) => {
      setState((current) => ({
        ...current,
        radius: clearCorners
          ? {
              all: value,
              bottomLeft: "",
              bottomRight: "",
              topLeft: "",
              topRight: "",
            }
          : { ...current.radius, all: value },
      }));
      dispatchInspectorEvent(
        "clue:inspector-property-change",
        {
          property: "radius.all",
          selectionType,
          value,
        },
        addressing,
      );
    },
    [addressing, selectionType],
  );

  const toggleSection = useCallback((section: InspectorSectionId) => {
    setState((current) => {
      const open = !current.openSections[section];
      dispatchInspectorEvent(
        "clue:inspector-section-toggle",
        {
          open,
          section,
          selectionType,
        },
        addressing,
      );
      return {
        ...current,
        openSections: {
          ...current.openSections,
          [section]: open,
        },
      };
    });
  }, [addressing, selectionType]);

  const requestAction = useCallback((action: string) => {
    dispatchInspectorEvent(
      "clue:inspector-action",
      {
        action,
        selectionType,
      },
      addressing,
    );
  }, [addressing, selectionType]);

  return {
    requestAction,
    setNestedValue,
    setPaddingAxis,
    setRadiusAll,
    setValue,
    state,
    toggleSection,
  };
}

export function useInspectorLayerTree(
  initialActiveLayer: string,
  initialExpandedLayers: string[] = [],
  selectionType: ChatShellInspectorSelection = "canvas",
) {
  const [activeLayer, setActiveLayer] = useState(initialActiveLayer);
  const [expandedLayers, setExpandedLayers] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(initialExpandedLayers.map((layer) => [layer, true])),
  );

  const toggleLayer = useCallback((layer: string) => {
    setExpandedLayers((current) => {
      const expanded = !current[layer];
      dispatchInspectorEvent("clue:inspector-layer-toggle", {
        expanded,
        layerId: layer,
        selectionType,
      });
      return { ...current, [layer]: expanded };
    });
  }, [selectionType]);

  const selectLayer = useCallback((layer: string) => {
    setActiveLayer(layer);
    dispatchInspectorEvent("clue:inspector-layer-select", {
      layerId: layer,
      selectionType,
    });
  }, [selectionType]);

  return { activeLayer, expandedLayers, selectLayer, toggleLayer };
}
