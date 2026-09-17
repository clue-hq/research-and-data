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
/**
 * AD4.B step 1 (§1.4/OQ-2): the Width/Height mode select's three DISPLAY
 * labels. The engine's own `Dimension.kind` is lowercase snake
 * (`fixed|hug|fill|token`) and the seam between the two is the write adapter's
 * (`scene-apply.ts`), exactly as `VALIGN_VALUES` and `IMAGE_FIT_VALUES` already
 * sit between the dummy's vocabulary and the engine's.
 *
 * `scene-hydrate.ts`'s `SceneSizeMode` is an alias of this type rather than a
 * second declaration of the same three strings — the adapter already imports
 * this module for `InspectorPresentationState`, so there is one statement of
 * the vocabulary and the two cannot drift.
 */
export type InspectorSizeMode = "Fill" | "Fixed" | "Hug";
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
  /**
   * AD4.B step 1 — RULING 14's deferred "final home", settled.
   *
   * These ten keys (`alignX`, `alignY`, `grow`, `height`, `heightFixed`,
   * `heightMode`, `opacity`, `width`, `widthFixed`, `widthMode`) were parked in
   * `scene-hydrate.ts`'s `SceneInspectorExtraState` because the co-founder's
   * four ad schemas shipped as STATIC scaffolding with no controller behind
   * them: a hydrated value with no state field could not reach a control, and
   * inventing the field before the control existed would have been speculative.
   * Binding §1.4's Layout section is what gives them one, so they move here
   * beside their siblings — the same path `customWidth`/`customHeight` took at
   * AD4.0 step 1 and `tokenStrokeColor` at step 3. What is LEFT in
   * `SceneInspectorExtraState` is only what is genuinely not a control:
   * `title` (the header's text) and `valignDisabled` (a display fact).
   *
   * `grow`/`alignX`/`alignY` are typed and defaulted here but are NOT bound to
   * a control until step 2 (the Auto Layout section): they hydrate today, so
   * giving them their field now is what keeps the model one statement rather
   * than two half-migrations.
   *
   * The DEFAULTS below are the dummy's own scaffolding values, verbatim, so
   * the fixture (non-hydrated) path renders exactly what it rendered before.
   */
  alignX: string;
  alignY: string;
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
  /** Rung A (rich-text plan, 2026-08-24): what a text node SAYS — its stored
   * `TextNode.content`, which the ad text schema's first Typography row edits.
   * The dummy schemas never authored a content control, so its default below is
   * the honest empty string rather than invented copy; only a text node
   * hydrates it. Multiline is real: the row is a textarea, not an input. */
  content: string;
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
  /** §1.4's Auto Layout Grow input (step 2 binds it). */
  grow: string;
  /**
   * §1.4's Dimensions H box — the height the node HAS: its fixed value when the
   * axis is fixed, else the solved layout bounds. Distinct from `heightFixed`,
   * which is the Fixed-mode-only input and is empty on a hug or fill axis: the
   * W/H boxes are shown in every mode, so a shared key would leave them blank
   * (or, before AD4.B, showing the scaffolding's invented `100`) on exactly the
   * nodes whose size the user most needs to read.
   */
  height: string;
  /** §1.4/OQ-2: the "Height fixed" input — empty unless the mode is Fixed. */
  heightFixed: string;
  /** §1.4/OQ-2: Fixed | Hug | Fill. */
  heightMode: InspectorSizeMode;
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
  /** §1.4/OQ-3: opacity as the DISPLAYED percent. The engine's 0–1 conversion
   * is the write adapter's, at the seam. */
  opacity: string;
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
  /** §1.4's Dimensions W box — see `height`. */
  width: string;
  /** §1.4/OQ-2: the "Width fixed" input — empty unless the mode is Fixed. */
  widthFixed: string;
  /** §1.4/OQ-2: Fixed | Hug | Fill. */
  widthMode: InspectorSizeMode;
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
  // AD4.B step 1: the ad dummy schemas' own scaffolding values, moved here
  // verbatim from the static markup they were written into
  // (`ad-dummy-inspectors.tsx`: `STATIC_ZERO`/`STATIC_SIZE`, the two align
  // selects' single options, the "Fixed" mode selects, the `100` opacity) — the
  // `customWidth`/`customHeight` precedent above, applied to ten more fields.
  // The fixture path therefore renders exactly what it rendered before; a real
  // node hydrates every one of them (`scene-hydrate.ts`), so none of these
  // numbers is ever shown over a document.
  alignX: "Space between",
  alignY: "Center",
  altText: "",
  // Founder ruling 2026-09-04: neutral seeds — a page with no theme renders
  // white on black, and nothing here may be a sample site's brand colour.
  backgroundColor: "#FFFFFF",
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
  content: "",
  // The dummy's own Custom W/H seeds, moved here verbatim from the local
  // `useState` pair they used to live in (`image-inspector.tsx`).
  customHeight: "1200",
  customWidth: "1200",
  direction: "horizontal",
  fillMode: "Fit",
  fontFamily: "Inter",
  fontSize: "24",
  fontWeight: "Semi Bold",
  grow: "0",
  height: "100",
  heightFixed: "100",
  heightMode: "Fixed",
  horizontalAlignment: "left",
  iconName: "Apple",
  iconSize: "Large",
  iconStroke: "Default",
  imagePreviewSrc: "/icons/chat-shell/inspector/web/image-preview.png",
  layoutMode: "Flex",
  locked: false,
  opacity: "100",
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
  textColor: "#000000",
  textStyle: "Body",
  lineSpacing: "normal",
  tokenBackgroundColor: "White",
  tokenStrokeColor: "",
  tokenTextColor: "Content",
  url: "",
  verticalAlignment: "top",
  visible: true,
  width: "100",
  widthFixed: "100",
  widthMode: "Fixed",
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

/** Exported for the addressing unit test and for the ad text inspector's
 * Fit-to-text button (a one-shot property change with no state key of its
 * own); every other production caller goes through the controller hooks. */
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
   *
   * LOAD-BEARING DEPENDENCY: live mode assumes the caller's `hydrated` never
   * transiently goes null for a mounted real document. On the ad lane that
   * holds because `use-scene-document.ts` keeps the old scene mounted through a
   * reload — a reload-token bump refetches without resetting the load state to
   * `loading` — so the session's hydration memo cannot yield null mid-reload.
   * A future loading-state refactor that breaks that would flash the
   * mount-mode defaults through every bound field.
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
  // design-editor hydrate adapter).
  //
  // AD4.R: what this prop MEANS now depends on `options.liveHydration`. Under
  // it, the prop is composed into the returned state PER RENDER — the accepted
  // engine scene owns every key it carries, so a document change re-derives
  // those values with no remount and no local copy in between. WITHOUT the
  // option it is still the MOUNT SEED it shipped as, merged over the dummy
  // defaults once and owned locally thereafter — the web inspector's and the
  // dummy fixture paths' contract, pending the web lane's own migration.
  // Either way callers keep remounting the inspector per selection (keyed on
  // the selected node), exactly how the dummy swaps schema views; in live mode
  // that remount survives to reset UI state (open sections, field drafts)
  // rather than to re-seed document values.
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
