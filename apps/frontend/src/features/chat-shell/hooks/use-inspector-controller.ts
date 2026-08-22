"use client";

import { useCallback, useMemo, useState } from "react";
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

// `justify` is the ad text schema's §2-row-2 fourth toggle. The web inspector
// still offers three (its own options list is unchanged), and the web write
// adapter's `ALIGNMENT_VALUES` guard already refuses anything outside them.
export type HorizontalAlignment = "center" | "justify" | "left" | "right";
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

/**
 * Ruling A7, applied to the gradient editor's numeric fields (AD4.0 step 2):
 * what one of them commits on blur/Enter — the clamped number, or `null` for
 * text that states no number at all.
 *
 * Those fields used to write per KEYSTROKE: clearing the angle box and typing
 * `137` persisted four document versions and four undo steps, one of them a
 * spurious `angle: 0` the user never intended (the old inline
 * `clamp(Number(value) || 0, …)` turned "" and "abc" into 0). `null` is the
 * honest answer for mid-edit text — "", "-", "1e" — and commits nothing, so
 * the field falls back to the value the document has instead of inventing one.
 * The clamp itself is unchanged: it is the dummy's own range for that field.
 */
export function commitInspectorNumber(raw: string, max: number): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return null;
  }
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return Math.min(max, Math.max(0, parsed));
}

export interface InspectorPresentationState {
  /** AD4.A step 3 (§1.3 row 2): the image's alt text — the AI suite's one
   * manual row. The fourth field this ad work has had to add to the dummy's
   * model under ruling 14's "final home" rule (step 1 added
   * `customWidth`/`customHeight`, step 3 of AD4.0 added `tokenStrokeColor`),
   * because the dummy's image schema shipped no such control and so authored
   * no fixture for it — which is why its default below is the honest empty
   * string rather than an invented description. */
  altText: string;
  backgroundColor: string;
  backgroundFill: InspectorBackgroundFill;
  buttonLabel: string;
  /** AD4.0 §1.1 row 1: the Custom size preset's H input (px). Ruling 14 parked
   * this pair with no state field while the control was inert; binding it to
   * the write seam is what gives it one. */
  customHeight: string;
  /** AD4.0 §1.1 row 1: the Custom size preset's W input (px). */
  customWidth: string;
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
  /** AD4.0 step 3 (§1.6): the brand token bound to the STROKE paint — the ad
   * lane's Stroke swatch writes through it, exactly as the two fields above
   * carry the text and background bindings. It is the third field this ad
   * work has had to add to the dummy's model (ruling 14's "final home" rule;
   * step 1 added `customWidth`/`customHeight` the same way), because the web
   * lane has no stroke control and so authored no fixture for it — which is
   * also why its default below is the honest empty string rather than one of
   * the dummy's invented token labels. */
  tokenStrokeColor: string;
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

export const DEFAULT_STATE: InspectorPresentationState = {
  altText: "",
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
  // The dummy's own Custom W/H seeds, moved here verbatim from the local
  // `useState` pair they used to live in (`image-inspector.tsx`).
  customHeight: "1200",
  customWidth: "1200",
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
  // Contract §2.1: preset values corrected (1024x1024 was retired at ratification).
  sizePreset: "Linkedin square (1:1) - 1200x1200",
  strokeColor: "none",
  strokeWidth: "1",
  textColor: "#00F59B",
  textStyle: "Body",
  lineSpacing: "normal",
  tokenBackgroundColor: "White",
  tokenStrokeColor: "",
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

export interface InspectorControllerOptions {
  /**
   * AD4.R: the MVP state model. When true, the returned `state` is composed
   * PER RENDER as `{...uiState, ...hydrated}` (openSections excepted — those
   * are UI facts the panel owns), and every value setter dispatches its write
   * event WITHOUT recording the value locally: the document answers through
   * the next hydration, which on the ad lane arrives in the same React batch
   * (the Task-1 synchronous mirror). False (the default) is the original
   * mount-seeded behavior, byte-for-byte — the web inspector and the dummy
   * fixture paths run on it unchanged, pending the web lane's own migration.
   */
  liveHydration?: boolean;
}

/**
 * The pure per-render composition behind `liveHydration`. `hydrated` — the
 * accepted scene's own values — wins every key it carries, EXCEPT
 * `openSections`, which is a UI fact the panel owns and hydration never
 * controls.
 */
export function composeInspectorState(
  uiState: InspectorPresentationState,
  hydrated: Partial<InspectorPresentationState> | undefined,
): InspectorPresentationState {
  if (!hydrated) return uiState;
  return { ...uiState, ...hydrated, openSections: uiState.openSections };
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
  // AD4.R: opt-in live hydration. Off by default — nothing below changes.
  options?: InspectorControllerOptions,
) {
  const live = options?.liveHydration === true;
  const [uiState, setUiState] = useState<InspectorPresentationState>(() => ({
      ...DEFAULT_STATE,
      ...hydrated,
      openSections: {
      ...DEFAULT_OPEN_SECTIONS,
      ...Object.fromEntries(collapsedSections.map((section) => [section, false])),
      ...hydrated?.openSections,
    },
  }));

  // Default mode returns the locally recorded state untouched; live mode
  // re-derives it from the caller's per-render `hydrated` snapshot.
  const state = useMemo(
    () => (live ? composeInspectorState(uiState, hydrated) : uiState),
    [hydrated, live, uiState],
  );

  const setValue = useCallback(
    <Key extends keyof InspectorPresentationState>(
      key: Key,
      value: InspectorPresentationState[Key],
    ) => {
      if (!live) {
        setUiState((current) => ({ ...current, [key]: value }));
      }
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
    [addressing, live, selectionType],
  );

  const setNestedValue = useCallback(
    <Key extends "padding" | "position" | "radius">(
      key: Key,
      nestedKey: keyof InspectorPresentationState[Key],
      value: string,
    ) => {
      if (!live) {
        setUiState((current) => ({
          ...current,
          [key]: { ...current[key], [nestedKey]: value },
        }));
      }
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
    [addressing, live, selectionType],
  );

  // W3.2 (R3): the two-axis padding path — one committed axis value updates
  // both sides and dispatches a single `padding.x`/`padding.y` event (the
  // write adapter's vocabulary). Used by the axis-collapsed padding boxes.
  const setPaddingAxis = useCallback(
    (axis: "x" | "y", value: string) => {
      if (!live) {
        setUiState((current) => ({
          ...current,
          padding:
            axis === "x"
              ? { ...current.padding, left: value, right: value }
              : { ...current.padding, bottom: value, top: value },
        }));
      }
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
    [addressing, live, selectionType],
  );

  // W4.2 (founder ruling F2, 2026-08-18): the all-corners radius commit. ONE
  // `radius.all` event — the write path's F2 chain clears the four per-corner
  // overrides inside the same operation, so when it does (`clearCorners`) the
  // corner fields mirror that here rather than keep showing overrides the
  // document no longer carries. Dispatching four corner events instead would
  // also lose three of them to the one-in-flight write discipline.
  const setRadiusAll = useCallback(
    (value: string, clearCorners: boolean) => {
      if (!live) {
        setUiState((current) => ({
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
      }
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
    [addressing, live, selectionType],
  );

  const toggleSection = useCallback((section: InspectorSectionId) => {
    setUiState((current) => {
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
