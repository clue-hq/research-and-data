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
  tokenBackgroundColor: "White",
  tokenTextColor: "Content",
  url: "",
  verticalAlignment: "top",
  visible: true,
  gap: "0",
  wrap: true,
};

function dispatchInspectorEvent(
  name: string,
  detail: Record<string, unknown>,
) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(name, { detail }));
}

export function useInspectorController(
  collapsedSections: InspectorSectionId[] = [],
  selectionType: ChatShellInspectorSelection = "canvas",
) {
  const [state, setState] = useState<InspectorPresentationState>(() => ({
      ...DEFAULT_STATE,
      openSections: {
      ...DEFAULT_OPEN_SECTIONS,
      ...Object.fromEntries(collapsedSections.map((section) => [section, false])),
    },
  }));

  const setValue = useCallback(
    <Key extends keyof InspectorPresentationState>(
      key: Key,
      value: InspectorPresentationState[Key],
    ) => {
      setState((current) => ({ ...current, [key]: value }));
      dispatchInspectorEvent("clue:inspector-property-change", {
        property: key,
        selectionType,
        value,
      });
    },
    [selectionType],
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
      dispatchInspectorEvent("clue:inspector-property-change", {
        property: `${key}.${String(nestedKey)}`,
        selectionType,
        value,
      });
    },
    [selectionType],
  );

  const toggleSection = useCallback((section: InspectorSectionId) => {
    setState((current) => {
      const open = !current.openSections[section];
      dispatchInspectorEvent("clue:inspector-section-toggle", {
        open,
        section,
        selectionType,
      });
      return {
        ...current,
        openSections: {
          ...current.openSections,
          [section]: open,
        },
      };
    });
  }, [selectionType]);

  const requestAction = useCallback((action: string) => {
    dispatchInspectorEvent("clue:inspector-action", {
      action,
      selectionType,
    });
  }, [selectionType]);

  return { requestAction, setNestedValue, setValue, state, toggleSection };
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
