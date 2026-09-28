"use client";

import Image from "next/image";
import { useState, type ReactNode } from "react";
import type { ZOrderAction } from "@/features/design-editor/adapter/scene-arrange";
import { backgroundFillCommits } from "@/features/design-editor/adapter/scene-hydrate";
import type { SceneImageAiBinding } from "@/features/design-editor/adapter/scene-image-ai";
import { PAGELESS_SCENE_NOTICE } from "@/features/design-editor/adapter/scene-pageless";
import type { ScenePalette } from "@/features/design-editor/adapter/scene-palette";
import type { AlignMode } from "@/features/design-editor/engine/scene/alignDistribute";
import type { SceneArrangeBinding } from "@/features/design-editor/hooks/use-scene-arrange";
import type { SceneAssetLibraryBinding } from "@/features/design-editor/hooks/use-scene-asset-library";
import type { ChatShellInspectorSelection } from "../model/chat-shell";
import {
  dispatchInspectorEvent,
  useInspectorController,
  useInspectorLayerTree,
  type HorizontalAlignment,
  type InspectorBackgroundFill,
} from "../hooks/use-inspector-controller";
import {
  BackgroundFillControl,
  ColorControl,
  InspectorField,
  InspectorHeader,
  InspectorIcon,
  type InspectorIconName,
  InspectorImageUpload,
  InspectorInput,
  InspectorLayerRow,
  InspectorSection,
  InspectorSelect,
  InspectorTextArea,
  RadiusControls,
} from "./inspector-primitives";
import styles from "./chat-shell.module.css";
// AD4.B step 3: the §1.6 colour machinery this file used to declare, moved to
// its own module so `ad-dummy-inspectors.tsx` can use the same row (importing
// it from here would be a cycle). A pure move — every call site below is
// unchanged, and the provider still wraps the whole panel from this file.
import {
  ScenePaletteContext,
  useAdColorRow,
  useScenePalette,
  useScenePaletteOptions,
} from "./inspector-color-row";
import {
  AdDummyInspector,
  AdSceneLayers,
  isAdDummyInspectorSelection,
  type AdHydrationBinding,
  type AdLayersBinding,
} from "./ad-dummy-inspectors";

// §2 delta (contract row 3): the font family list is prop-fed — the real
// library/kit vocabulary arrives with hydration; the dummy's hardcoded
// Satoshi/Season Serif/DM Mono entries are gone.
const DEFAULT_FONT_OPTIONS = ["Inter"] as const;
// §2 delta (contract row 2): the nine named weights replace the dummy's four.
const FONT_WEIGHT_OPTIONS = [
  "100 Thin",
  "200 Extra Light",
  "300 Light",
  "400 Regular",
  "500 Medium",
  "600 Semi Bold",
  "700 Bold",
  "800 Extra Bold",
  "900 Black",
] as const;
// §2 delta (contract row 4): Stretch/Tile are dropped; Crop arrives (its focal
// control is Lane A, behind Gate G-C).
const FILL_MODES = ["Fit", "Fill", "Crop"] as const;
// §2 delta (contract row 1): the LinkedIn square's real pixels (1200x1200) and
// a Custom entry that reveals W/H.
const SIZE_PRESETS = [
  "Linkedin square (1:1) - 1200x1200",
  "Instagram portrait (4:5) - 1080x1350",
  "Story (9:16) - 1080x1920",
  "Custom",
] as const;

type AdSchemaBinding = AdLayersBinding & AdHydrationBinding;

const AD_INSPECTOR_TITLES: Partial<
  Record<ChatShellInspectorSelection, string>
> = {
  "auto-layout": "Auto layout",
  canvas: "Canvas",
  ellipse: "Ellipse",
  group: "Group",
  image: "Image1",
  rectangle: "Rectangle",
  text: "Text34",
};

type AdSelectableLayer =
  | "auto-layout"
  | "button"
  | "ellipse"
  | "group"
  | "image"
  | "rectangle"
  | "text";

function AdLayers({
  layers,
  onSelectionChange,
  selected,
  ...binding
}: AdLayersBinding & {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  selected: ChatShellInspectorSelection;
}) {
  const tree = useInspectorLayerTree(selected, ["group"], selected);

  const select = (layer: string, selection?: AdSelectableLayer) => {
    tree.selectLayer(layer);
    if (selection) onSelectionChange(selection);
  };

  // AD2.6: the real scene tree replaces the fixture rows below, using the same
  // `InspectorLayerRow` primitive with the same props. The fixture branch stays
  // as the dummy shipped it and is what renders until AD2.7 feeds `layers`.
  if (layers) {
    return <AdSceneLayers layers={layers} {...binding} />;
  }

  return (
    <div className={styles.layerList}>
      <InspectorLayerRow
        active={tree.activeLayer === "auto-layout"}
        icon="layout-template"
        label="Auto layout"
        onClick={() => select("auto-layout", "auto-layout")}
      />
      <InspectorLayerRow
        active={tree.activeLayer === "text-primary"}
        icon="type"
        label="Text"
        onClick={() => select("text-primary", "text")}
      />
      <InspectorLayerRow
        active={tree.activeLayer === "text"}
        icon="type"
        label="Text"
        onClick={() => select("text", "text")}
        trailing
      />
      <InspectorLayerRow
        expanded={tree.expandedLayers.group}
        expandable
        active={tree.activeLayer === "group"}
        icon="square-dashed"
        label="Group"
        onClick={() => {
          tree.selectLayer("group");
          tree.toggleLayer("group");
          onSelectionChange("group");
        }}
      />
      {tree.expandedLayers.group ? (
        <>
          <InspectorLayerRow depth={1} icon="type" label="Text" onClick={() => select("group-text", "text")} />
          <InspectorLayerRow depth={1} icon="rectangle" label="Rectangle" onClick={() => select("group-rectangle", "rectangle")} />
        </>
      ) : null}
      <InspectorLayerRow active={tree.activeLayer === "rectangle"} icon="rectangle" label="Rectangle" onClick={() => select("rectangle", "rectangle")} />
      <InspectorLayerRow active={tree.activeLayer === "ellipse"} icon="ellipse" label="Ellipse" onClick={() => select("ellipse", "ellipse")} />
      <InspectorLayerRow active={tree.activeLayer === "image"} icon="image" label="Image" onClick={() => select("image", "image")} />
      <InspectorLayerRow active={tree.activeLayer === "image-secondary"} icon="image" label="Image" onClick={() => select("image-secondary", "image")} />
      <InspectorLayerRow active={tree.activeLayer === "button"} icon="rectangle" label="Button" onClick={() => select("button", "button")} />
    </div>
  );
}

function TextAlignment({
  disabled = false,
  horizontal,
  onHorizontalChange,
  onVerticalChange,
  vertical,
}: {
  /** G-H (AD4.R-10): these seven toggles are value controls — each one writes an
   * alignment — so they go dark with the rest of the panel. */
  disabled?: boolean;
  horizontal: HorizontalAlignment;
  onHorizontalChange: (value: HorizontalAlignment) => void;
  onVerticalChange: (value: "bottom" | "middle" | "top") => void;
  vertical: "bottom" | "middle" | "top";
}) {
  // §2 delta (contract row 2): H-alignment gains a fourth Justify toggle.
  const horizontalOptions = [
    ["left", "align-left"],
    ["center", "align-center"],
    ["right", "align-right"],
    ["justify", "align-justify"],
  ] as const;
  const verticalOptions = [
    ["top", "align-top"],
    ["middle", "align-middle"],
    ["bottom", "align-bottom"],
  ] as const;

  return (
    <div className={styles.alignmentGroups}>
      <div aria-label="Horizontal alignment" className={`${styles.alignmentControl} ${styles.alignmentControlQuad} ${disabled ? styles.inspectorControlDisabled : ""}`} role="group">
        {horizontalOptions.map(([value, icon]) => (
          <button aria-label={`Align ${value}`} aria-pressed={horizontal === value} className={horizontal === value ? styles.alignmentActive : ""} disabled={disabled} key={value} onClick={() => onHorizontalChange(value)} type="button">
            <InspectorIcon name={icon} size={12} />
          </button>
        ))}
      </div>
      <div aria-label="Vertical alignment" className={`${styles.alignmentControl} ${styles.verticalAlignment} ${disabled ? styles.inspectorControlDisabled : ""}`} role="group">
        {verticalOptions.map(([value, icon]) => (
          <button aria-label={`Align ${value}`} aria-pressed={vertical === value} className={vertical === value ? styles.alignmentActive : ""} disabled={disabled} key={value} onClick={() => onVerticalChange(value)} type="button">
            <InspectorIcon name={icon} size={12} />
          </button>
        ))}
      </div>
    </div>
  );
}

/** G-H (AD4.R-10): layer order and alignment actions are OPERATIONS on the
 * document (not navigation), so the whole grid goes dark while the panel is
 * disabled.
 *
 * AD4.B step 4 (§1.5): the two tables carry the typed action each button
 * performs, and `arrange` — when the session supplies it — is what they call.
 * Its per-action enablement disables the buttons this selection cannot use, so
 * an edge of the stack or a single-node selection is stated rather than
 * silently refused. ABSENT (the dummy fixture path) keeps the original
 * `requestAction("arrange:…")` dispatch byte for byte, dead listener and all —
 * the AD4.A posture for a control whose live path is not armed. */
function ArrangeControls({
  arrange,
  disabled = false,
  onAction,
}: {
  arrange?: SceneArrangeBinding;
  disabled?: boolean;
  onAction: (action: string) => void;
}) {
  const layerActions = [
    ["Bring to front", "align-top", "front"],
    ["Bring forward", "align-middle", "forward"],
    ["Send backward", "align-center", "backward"],
    ["Send to back", "align-bottom", "back"],
  ] as const satisfies readonly (readonly [string, InspectorIconName, ZOrderAction])[];
  const alignmentActions = [
    ["Align left", "align-left", "left"],
    ["Align center", "align-center", "center-h"],
    ["Align right", "align-right", "right"],
    ["Align top", "align-top", "top"],
    ["Align middle", "align-middle", "middle-v"],
    ["Align bottom", "align-bottom", "bottom"],
  ] as const satisfies readonly (readonly [string, InspectorIconName, AlignMode])[];

  // The G-H-approved disabled treatment (`.inspectorControlDisabled`, the
  // sheet's own 0.45) reused verbatim — no rule is authored here. WHICH ELEMENT
  // WEARS IT is the whole decision: the panel-level `disabled` dims the GRID
  // (its frame is part of the same statement, and every button inside is off
  // anyway — the T10 behaviour, unchanged); a button that only THIS SELECTION
  // cannot use wears it alone. The two are mutually exclusive by construction,
  // so they can never stack into an opacity nobody authored.
  const dim = (off: boolean) =>
    off && !disabled ? styles.inspectorControlDisabled : "";

  return (
    <>
      <InspectorField label="Layer">
        <div className={`${styles.inspectorActionGrid} ${styles.inspectorActionGridFour} ${disabled ? styles.inspectorControlDisabled : ""}`}>
          {layerActions.map(([label, icon, action]) => {
            const off = disabled || (arrange ? !arrange.enablement.zOrder[action] : false);
            return <button aria-label={label} className={dim(off)} disabled={off} key={label} onClick={() => (arrange ? arrange.zOrder(action) : onAction(label))} type="button"><InspectorIcon name={icon} size={12} /></button>;
          })}
        </div>
      </InspectorField>
      <InspectorField label="Alignment">
        <div className={`${styles.inspectorActionGrid} ${styles.inspectorActionGridSix} ${disabled ? styles.inspectorControlDisabled : ""}`}>
          {alignmentActions.map(([label, icon, mode]) => {
            const off = disabled || (arrange ? !arrange.enablement.align : false);
            return <button aria-label={label} className={dim(off)} disabled={off} key={label} onClick={() => (arrange ? arrange.align(mode) : onAction(label))} type="button"><InspectorIcon name={icon} size={12} /></button>;
          })}
        </div>
      </InspectorField>
    </>
  );
}

// (`PaddingControls` lived here for the button schema's Layout section; both
// went with the row-7 button-schema removal.)

function Section({
  children,
  id,
  label,
  open,
  toggle,
}: {
  children?: ReactNode;
  id: Parameters<ReturnType<typeof useInspectorController>["toggleSection"]>[0];
  label: string;
  open: boolean;
  toggle: () => void;
}) {
  // `compact` left with its only callers (the §2.7-removed "Link to" sections).
  return <InspectorSection key={id} label={label} onOpenChange={toggle} open={open}>{children}</InspectorSection>;
}

function AdTextInspector({
  addressing,
  arrange,
  fontOptions,
  hydrated,
  inspectorDisabled = false,
  locked = false,
  onSelectionChange,
  ...binding
}: AdSchemaBinding & {
  /** §1.5 (AD4.B step 4): the session's Arrange actions. Absent keeps this
   * section's original `requestAction` dispatch. */
  arrange?: SceneArrangeBinding;
  fontOptions: readonly string[];
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
}) {
  // G-H (AD4.R-10): one expression for every write control in this schema — the
  // node's own lock (upstream's `disabled={selectedNode.locked}` posture) OR the
  // in-flight agent turn. The Layers section below is navigation and takes
  // neither.
  const inert = locked || inspectorDisabled;
  // The shared dummy default ("Semi Bold") is not one of the §2-row-2 named
  // weights, so this schema opens on the matching nine-name value. The web
  // inspector keeps its own four-name list and the untouched shared default.
  // A hydrated weight is a real one and wins; a node whose weight is off the
  // nine-name ramp hydrates none (AD2.4) and keeps this default.
  const initial = { fontWeight: "600 Semi Bold", ...hydrated };
  const typographyUnavailable = hydrated?.typographyUnavailable === true;
  const typographyInert = inert || typographyUnavailable;
  const controller = useInspectorController([], "text", initial, addressing, {
    // AD4.R: live only when a real scene is behind the panel — the dummy
    // fixture path (no hydration) stays the interactive mock it shipped as.
    // The flag reads the `hydrated` PROP, never `initial`, which is always
    // non-null because it carries this schema's own default. `initial` is
    // rebuilt from the live prop every render, so it is the live merge source
    // too: the schema-default key rides along and wins only when hydration
    // does not carry it — today's mount semantics, extended to every render.
    liveHydration: hydrated != null,
  });
  const { requestAction, setNestedValue, setValue, state, toggleSection } = controller;
  const paletteOptions = useScenePaletteOptions();
  // §1.6: the two colour rows this schema owns. Brand swatches are offered
  // FIRST — they ARE the Theme tab, the tab `ColorControl` opens on, with
  // custom hex behind the second one — and a pick writes a token while a hex
  // writes a literal and detaches the binding (the ratified, informed trade).
  const colorRow = useAdColorRow({
    hydratedValue: state.textColor,
    onHex: (hex) => setValue("textColor", hex),
    onToken: (label) => setValue("tokenTextColor", label),
    paletteOptions,
  });
  // The same row on the stroke paint. `none` is a real hydrated value here (a
  // strokeless node) and names no token, so it stands as it is.
  //
  // RULING A9 makes this row's two fields move TOGETHER — a colour on a
  // strokeless node mints a width, a width on one mints a colour — and under
  // live hydration BOTH halves simply read the minted scene back: the write is
  // the single statement of the mint (`scene-apply.ts`, which owns the two
  // numbers), and the accepted document re-derives `state.strokeColor` /
  // `state.strokeWidth` in the same batch. The display mirrors this schema used
  // to keep (a local width copy re-seeded from `mintedStrokeWidth`, a `setShown`
  // push from `mintedStrokeColor`) were the mount-seeded model's patch for a gap
  // that no longer exists.
  const strokeRow = useAdColorRow({
    hydratedValue: state.strokeColor,
    onHex: (hex) => setValue("strokeColor", hex),
    onToken: (label) => setValue("tokenStrokeColor", label),
    paletteOptions,
  });

  return (
    <>
      <Section id="typography" label="Typography" open={state.openSections.typography} toggle={() => toggleSection("typography")}>
        {/* Rung A (rich-text plan, 2026-08-24): what the node SAYS, first —
            every other row on this panel styles text the user could not edit.
            It COMMITS ON BLUR/⌘-Enter (`InspectorTextArea`), never per
            keystroke: a per-keystroke content field would persist one document
            version and one undo step per letter.

            The guard shape is the Alt-text row's, verbatim: `inspectorDisabled`
            rides as its OWN line so the locked half stays the literal
            `if (!locked)` the A29 pin reads. The field is natively disabled, so
            this is the programmatic-blur backstop. */}
        <InspectorField label="Text">
          <InspectorTextArea
            ariaLabel="Text content"
            disabled={inert}
            onCommitValue={(value) => { if (inspectorDisabled) return; if (!locked) setValue("content", value); }}
            value={state.content}
          />
        </InspectorField>
        <InspectorField label="Color"><ColorControl color={colorRow.color} disabled={inert} onColorChange={colorRow.onColorChange} onTokenChange={colorRow.onTokenChange} options={paletteOptions} /></InspectorField>
        <InspectorField label="Font"><InspectorSelect disabled={typographyInert} label="Font family" onChange={(value) => setValue("fontFamily", value)} options={fontOptions} value={typographyUnavailable ? "" : state.fontFamily} /></InspectorField>
        <div className={styles.fieldGrid}>
          {/* §2 delta (contract row 2): the size select becomes a free number. */}
          <InspectorField label="Size"><InspectorInput ariaLabel="Font size" disabled={typographyInert} onCommitValue={(value) => setValue("fontSize", value)} value={typographyUnavailable ? "" : state.fontSize} /></InspectorField>
          <InspectorField label="Weight"><InspectorSelect disabled={typographyInert} label="Font weight" onChange={(value) => setValue("fontWeight", value)} options={FONT_WEIGHT_OPTIONS} value={typographyUnavailable ? "" : state.fontWeight} /></InspectorField>
        </div>
        {typographyUnavailable ? <p className={styles.inspectorStatusNote} role="status">Brand typography is unavailable. If this persists, reload to try again.</p> : null}
        <InspectorField label="Alignment"><TextAlignment disabled={inert} horizontal={state.horizontalAlignment} onHorizontalChange={(value) => setValue("horizontalAlignment", value)} onVerticalChange={(value) => setValue("verticalAlignment", value)} vertical={state.verticalAlignment} /></InspectorField>
      </Section>
      <Section id="stroke" label="Stroke" open={state.openSections.stroke} toggle={() => toggleSection("stroke")}>
        <InspectorField label="Color"><ColorControl color={strokeRow.color} disabled={inert} onColorChange={strokeRow.onColorChange} onTokenChange={strokeRow.onTokenChange} options={paletteOptions} /></InspectorField>
        <InspectorField label="Width"><InspectorInput ariaLabel="Stroke width" disabled={inert} onCommitValue={(value) => setValue("strokeWidth", value)} value={state.strokeWidth} /></InspectorField>
      </Section>
      <Section id="layout" label="Layout" open={state.openSections.layout} toggle={() => toggleSection("layout")}>
        <InspectorField label="Position">
          <div className={styles.fieldGrid}>
            <InspectorInput ariaLabel="X position" disabled={inert} onCommitValue={(value) => setNestedValue("position", "x", value)} prefix="X" value={state.position.x} />
            <InspectorInput ariaLabel="Y position" disabled={inert} onCommitValue={(value) => setNestedValue("position", "y", value)} prefix="Y" value={state.position.y} />
          </div>
        </InspectorField>
        <InspectorField label="Rotation"><InspectorInput ariaLabel="Rotation" disabled={inert} onCommitValue={(value) => setValue("rotation", value)} suffix="°" value={state.rotation} /></InspectorField>
        {/* Plan 4 item F: the one-click way out of a fixed height the copy
            outgrew (the selection then outlines the glyphs and drops its
            dashed frame). One property-change event, one write — two
            `setValue` calls would be two document versions and the second
            can be dropped by the one-in-flight write discipline. Dead while
            the box already hugs. */}
        <InspectorField label="Text box">
          <button
            className={styles.sharePrimaryButtonWide}
            disabled={inert || state.heightMode === "Hug"}
            onClick={() => {
              if (inspectorDisabled || locked) return;
              dispatchInspectorEvent(
                "clue:inspector-property-change",
                { property: "fitToText", selectionType: "text", value: "1" },
                addressing,
              );
            }}
            type="button"
          >
            Fit to text
          </button>
        </InspectorField>
      </Section>
      <Section id="arrange" label="Arrange" open={state.openSections.arrange} toggle={() => toggleSection("arrange")}>
        <ArrangeControls arrange={arrange} disabled={inert} onAction={(action) => requestAction(`arrange:${action}`)} />
      </Section>
      <Section id="layers" label="Layers" open={state.openSections.layers} toggle={() => toggleSection("layers")}>
        <AdLayers onSelectionChange={onSelectionChange} selected="text" {...binding} />
      </Section>
    </>
  );
}

function AdCanvasInspector({
  addressing,
  hydrated,
  inspectorDisabled = false,
  onSelectionChange,
  pageless = false,
  ...binding
}: AdSchemaBinding & {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  /** genad2 Task 5: the open document has NO page yet (`pages: {}`) — see the
   * refusal below. */
  pageless?: boolean;
}) {
  // G-H (AD4.R-10): this schema addresses the PAGE, which has no node lock —
  // the header renders no lock button here at all (`elementActions` is false for
  // `canvas`), so the in-flight agent turn is this schema's only refusal, and
  // its controls gate on that flag alone rather than on an `inert` pair.
  // Pin the select to its own option list: the shared DEFAULT_STATE carries the
  // same corrected §2.1 string today, but this override keeps the schema's value
  // coupled to SIZE_PRESETS so a relabel can never orphan the <select>. A real
  // page hydrates its own preset (or "Custom") over it.
  const initial = { sizePreset: SIZE_PRESETS[0], ...hydrated };
  const controller = useInspectorController([], "canvas", initial, addressing, {
    // AD4.R live hydration, keyed on the `hydrated` prop — see the text
    // schema's controller for why the flag reads the prop and not `initial`.
    liveHydration: hydrated != null,
  });
  const { setValue, state, toggleSection } = controller;
  const palette = useScenePalette();
  const paletteOptions = useScenePaletteOptions();
  // §1.6: the Background section's colour row, through the same hook the text
  // and stroke rows use. Its `color` is what the solid swatch AND the gradient
  // preview are drawn from (a token name is not a CSS colour, so a
  // token-filled frame previewed as nothing), and its `value` is the raw
  // swatch value — the document's own — a mode switch decides from.
  const backgroundRow = useAdColorRow({
    hydratedValue: state.backgroundColor,
    onHex: (hex) => setValue("backgroundColor", hex),
    onToken: (label) => setValue("tokenBackgroundColor", label),
    paletteOptions,
  });
  // §1.1 row 2 / Ruling A15.2: the Background fill control's one handler. The
  // DECISION is pure and lives in the adapter (`backgroundFillCommits`, which
  // states the two browser-proven defects it fixes); this is only the dispatch,
  // exactly as `changeSizePreset` below is only the dispatch.
  //
  // A mode switch to Solid returns TWO commits — the type (so the control
  // renders the swatch) and the colour (the row that actually carries one) —
  // and they collapse to ONE document version, because a solid fill object maps
  // to no operation by contract. This is not a general re-hydrate mechanism: it
  // is this section's own handler keeping its two controls consistent with the
  // writes it dispatches.
  //
  // R3b (step 3): the seed reads `backgroundRow.value` — the value the swatch
  // is showing RIGHT NOW, which under live hydration IS the document's own
  // background (AD4.R-6 retired the row's draft). That is the exact fact the
  // write adapter reads off the node, so the switch decides against the
  // document rather than against a panel-local copy of it.
  //
  // The PALETTE rides in too, because that value may be a token's NAME rather
  // than a colour. `backgroundFillCommits` resolves it — and returns NO
  // commits when it cannot, which refuses the mode switch outright instead of
  // flipping the select over a write that can never land.
  const changeBackgroundFill = (next: InspectorBackgroundFill) => {
    for (const commit of backgroundFillCommits(
      state.backgroundFill,
      next,
      backgroundRow.value,
      palette,
    )) {
      if (commit.property === "backgroundColor") {
        // Through the ROW's own handler, not `setValue` directly: this is the
        // row's colour half, and the row is the one place that says what a
        // colour landing on this swatch dispatches.
        backgroundRow.onColorChange(commit.value);
      } else {
        setValue("backgroundFill", commit.value);
      }
    }
  };
  // AD4.R: "Custom" is a VIEW choice, not a document fact — it names no size,
  // writes nothing, and only reveals the W/H boxes (which read the live page
  // size hydrate always states). Everything else the select shows is the
  // document's own preset match. Picking a real preset dispatches the write
  // and drops the view choice; the document answers through hydration.
  const [customChosen, setCustomChosen] = useState(false);
  const shownPreset = customChosen ? "Custom" : state.sizePreset;
  const changeSizePreset = (label: string) => {
    if (label === "Custom") {
      setCustomChosen(true);
      return;
    }
    setCustomChosen(false);
    setValue("sizePreset", label);
  };
  // genad2 Task 5 (contract b): a document with NO page has no size, no preset
  // and no background — so this schema states none of them. Left to render, it
  // would show `DEFAULT_STATE`'s invented `Linkedin square` preset and its
  // `1200`/`1200` Custom boxes (the un-hydrated fixture seeds: a pageless scene
  // hydrates nothing, so every bound field falls back to them), which is the
  // exact "a field may not display a number the document does not have" defect
  // the AD4.0 review has now caught three times. The Layers section goes too —
  // a pageless document has no layers, and the fixture branch of `AdLayers`
  // would paint the dummy's tree over one.
  //
  // The refusal sits AFTER the hooks above and before the rows, deliberately:
  // an early return above them would reorder hooks on the turn that authors the
  // first page.
  //
  // FOUNDER-DESIGN FLAG (open): plain text in this panel's own existing note
  // idiom (`.inspectorStatusNote`, the same line the 409 reload note and the
  // write errors use). Whether the inspector should say anything here at all —
  // and if so in what treatment — is an unmade design decision; nothing styled
  // is invented for it. See `scene-pageless.ts`.
  if (pageless) {
    return (
      <p className={styles.inspectorStatusNote} role="status">
        {PAGELESS_SCENE_NOTICE}
      </p>
    );
  }
  return (
    <>
      <Section id="dimensions" label="Dimensions" open={state.openSections.dimensions} toggle={() => toggleSection("dimensions")}>
        <InspectorField label="Size"><InspectorSelect disabled={inspectorDisabled} label="Canvas dimensions" onChange={changeSizePreset} options={SIZE_PRESETS} value={shownPreset} /></InspectorField>
        {shownPreset === "Custom" ? (
          <InspectorField label="Custom size">
            {/* genad2 Task 6: `suffix` states the UNIT these two numbers are in
                — the page's own, hydrated (`pageDisplaySize`): `px` on the
                seeded ad, `mm` on an agent-authored A4, `in` on a US Letter.
                It is the inert-text idiom the Rotation (°) and Opacity (%)
                rows already use, and it is all this row gains: no unit
                selector, no orientation or bleed controls. Changing a page's
                unit is page SETUP, which the design agent owns.
                Read off `hydrated` rather than `state`, like the header's
                `title` — it is a display fact with no control behind it — so
                the dummy fixture path (no `hydrated`) renders exactly what it
                always did. The commit lands in this same unit. */}
            <div className={styles.fieldGrid}>
              <InspectorInput ariaLabel="Custom width" disabled={inspectorDisabled} onCommitValue={(value) => setValue("customWidth", value)} prefix="W" suffix={hydrated?.customSizeUnit} value={state.customWidth} />
              <InspectorInput ariaLabel="Custom height" disabled={inspectorDisabled} onCommitValue={(value) => setValue("customHeight", value)} prefix="H" suffix={hydrated?.customSizeUnit} value={state.customHeight} />
            </div>
          </InspectorField>
        ) : null}
      </Section>
      <Section id="background" label="Background" open={state.openSections.background} toggle={() => toggleSection("background")}>
        <InspectorField label="Fill">
          {/* §1.6: both of this control's pickers — the solid swatch and each
              gradient stop — offer the document's brand palette. Only the
              SOLID one writes a token: a gradient stop has no token row in the
              write table, so a brand pick there commits the colour it paints
              (`ColorStop.color` can hold a token, but nothing authors one
              through this control, and §8 authorizes no new mapping). */}
          <BackgroundFillControl
            disabled={inspectorDisabled}
            fill={state.backgroundFill}
           
            onFillChange={changeBackgroundFill}
            onSolidColorChange={backgroundRow.onColorChange}
            onTokenChange={backgroundRow.onTokenChange}
            options={paletteOptions}
            solidColor={backgroundRow.color}
          />
        </InspectorField>
      </Section>
      <Section id="layers" label="Layers" open={state.openSections.layers} toggle={() => toggleSection("layers")}>
        <AdLayers onSelectionChange={onSelectionChange} selected="canvas" {...binding} />
      </Section>
    </>
  );
}

/**
 * AD4.A step 3 (§1.3 row 2): the MVP editor's AI image suite, restyled in this
 * shell's own primitives and classes. Composition only — every control here is
 * an existing primitive or an existing class in the role it already plays:
 *
 *  • the two free-text fields are `InspectorField` + `InspectorInput`, exactly
 *    like every other typed row in this panel;
 *  • the action buttons are the shell's own authored button pair
 *    (`.sharePrimaryButtonWide` / `.shareSecondaryButton`, from the artifact
 *    share menu) — BORROWED, because the inspector has no labelled action
 *    button of its own: `.inspectorActionGrid` is an icon grid with 4- and
 *    6-column templates and 27px transparent pills, which a two- or
 *    three-text-button row cannot ride. The primary is the one button in this
 *    shell with an authored `:disabled` treatment, which this surface needs
 *    three times over (empty prompt, in flight, and the pending label) and
 *    which the A19 family forbids inventing;
 *  • the pairs sit in `.fieldGrid`, the inspector's own two-up row;
 *  • the candidate tile is `.imageReplaceField`, the Fill row's own image tile
 *    two rows above — a bordered box with a centred caption pill;
 *  • the two note lines are `.inspectorStatusNote`, the inspector's own note
 *    line, and every FAILURE goes to the panel's existing error slot instead
 *    (`writes.reportError`), never a second failure surface.
 *
 * No icons: upstream's buttons carry lucide glyphs, but this panel's icon
 * vocabulary is `InspectorIcon`'s local file list, so lucide inside it would be
 * new visual vocabulary rather than a borrow. Every string is upstream's own.
 *
 * The prompt and instruction are LOCAL DRAFTS consumed by a button press, so no
 * keystroke is ever a write; the staged candidate deliberately lives OUTSIDE
 * this component (in the session hook) because the panel remounts on every
 * reload, and a paid model result must not be thrown away by one.
 */
function AdImageAiRows({
  disabled,
  imageAi,
}: {
  /** G-H (AD4.R-10): the whole suite is spend — every button here starts a paid
   * model run or writes its result — so a locked node or an in-flight agent turn
   * closes all of it. Required (not defaulted): the only caller is the ad image
   * schema, and a suite that silently defaulted to enabled is exactly the defect
   * this gate exists to prevent. */
  disabled: boolean;
  imageAi: SceneImageAiBinding;
}) {
  const [prompt, setPrompt] = useState("");
  const [instruction, setInstruction] = useState("");
  const { candidate, canEdit, editing, generating, hasImage, savedNotice, statusLine } =
    imageAi;
  return (
    <>
      <InspectorField label={hasImage ? "Regenerate" : "Generate image"}>
        <InspectorInput
          ariaLabel="Image prompt"
          disabled={disabled}
          onChange={setPrompt}
          placeholder="e.g. editorial photo of a calm clinic reception, soft light, no text"
          value={prompt}
        />
      </InspectorField>
      {/* The pending label IS the status: `.sharePrimaryButtonWide:disabled`
          is the shell's authored waiting treatment (`cursor: wait`), and the
          share menu's own primary uses it the same way ("Publishing…"). */}
      <button
        className={styles.sharePrimaryButtonWide}
        disabled={disabled || generating || prompt.trim() === ""}
        onClick={() => imageAi.onGenerate(prompt)}
        type="button"
      >
        {generating ? "Generating…" : hasImage ? "Regenerate" : "Generate"}
      </button>
      {/* Upstream renders the edit block only when there is a real, ready
          source asset to edit (`canEdit`), and so does this — the alternative
          would be a permanently dead pair of buttons over a node with no
          pixels. When the block is missing over a NOT-READY asset, the status
          line below says why; over a LOCKED one, §4's silent-refusal posture
          says nothing, as it does for every other control on this panel. */}
      {canEdit ? (
        <>
          <InspectorField label="Edit image">
            <InspectorInput
              ariaLabel="Image edit instruction"
              disabled={disabled}
              onChange={setInstruction}
              placeholder="e.g. make the sky warmer, remove the person on the left"
              value={instruction}
            />
          </InspectorField>
          {candidate ? null : editing ? (
            // While an edit is in flight the two buttons are REPLACED by the
            // pending primary rather than disabled in place: `Remove
            // background` is a secondary, and the shell authored no disabled
            // treatment for one, so a disabled secondary would look live.
            <button className={styles.sharePrimaryButtonWide} disabled type="button">
              Applying edit…
            </button>
          ) : (
            <div className={styles.fieldGrid}>
              <button
                className={styles.sharePrimaryButtonWide}
                disabled={disabled || instruction.trim() === ""}
                onClick={() => imageAi.onEdit(instruction)}
                type="button"
              >
                Edit
              </button>
              {/* G-H RESIDUAL — ACCEPTED (controller, 2026-08-22), recorded
                  rather than papered over. The shell authored NO disabled
                  treatment for a secondary button (the reason the in-flight
                  branch above REPLACES this pair instead of disabling it), and
                  the class G-H approved is for FIELDS. Inventing a
                  secondary-button treatment here is exactly what the A19
                  never-invent-UI discipline forbids, so it was not done.
                  Consequence: `Remove background` (and `Reject` / `Save as new`
                  in the review below) are genuinely inert while an agent turn
                  runs, but do not dim. The OPERATION is prevented, which is the
                  founder's ruling; how a disabled secondary should LOOK is
                  founder-visible design and copy for a later pass. */}
              <button
                className={styles.shareSecondaryButton}
                disabled={disabled}
                onClick={imageAi.onRemoveBackground}
                type="button"
              >
                Remove background
              </button>
            </div>
          )}
        </>
      ) : null}
      {/* THE REVIEW IS A SIBLING OF THE EDIT BLOCK, NOT A CHILD — upstream's own
          structure (`ImageInspectorSection.tsx:253-297` vs `:299-349`), and the
          reason is exactly what nesting cost at review: `canEdit` folds in §4's
          lock, so locking the node while a candidate was staged removed
          Before/After, Accept, Reject and Save-as-new with nothing on screen to
          say where a paid result had gone. Accept still refuses while the node
          is locked — the refusal is the WRITE's, silent like every other on this
          lane — and unlocking makes it land, which is only true because the
          review outlived the lock. */}
      {candidate ? (
        <AdImageCandidateReview
          candidate={candidate}
          disabled={disabled}
          imageAi={imageAi}
          onClearInstruction={() => setInstruction("")}
        />
      ) : null}
      {savedNotice ? (
        <p className={styles.inspectorStatusNote} role="status">
          {savedNotice}
        </p>
      ) : null}
      {/* The asset status line — silent for a ready asset, because the Fill
          thumbnail above already shows the picture. It speaks in the two states
          nothing else states, which are also the two that explain a missing
          Edit block (`sceneImageStatusLine`). */}
      {statusLine ? (
        <p className={styles.inspectorStatusNote}>{statusLine}</p>
      ) : null}
    </>
  );
}

/**
 * §1.3 Review: the Before/After comparison an edit produces, and the three
 * answers to it.
 *
 * BOTH TILES, side by side, per the coordinator's ruling. The leaner reading
 * was that the Fill thumbnail two rows above already shows the current asset,
 * so a Before tile duplicates it — but §1.3's row names the control
 * ("Before/After candidate review"), and a comparison whose two halves are
 * separated by two form fields is a candidate preview beside a coincidence, not
 * a comparison. While the review is open, showing the picture twice IS the
 * point: this is what you have, this is what you would get.
 *
 * The tile is `.imageReplaceField` — the Fill row's own image tile, one section
 * up — and the caption pill it styles carries the two words instead of "Replace
 * image". Its 20% scrim exists to keep that pill readable and applies equally to
 * both halves, so it darkens the comparison without biasing it.
 *
 * NEITHER TILE FALLS BACK TO THE DUMMY'S STOCK PNG. `beforeSrc` is the node's
 * own asset resolved through the public passthrough, or null — a stranger's
 * photograph labelled "Before" would not be a wrong thumbnail, it would be a
 * wrong ANSWER to the question this panel is asking.
 *
 * Accept applies the same `[upsert_asset, place_asset_in_node]` pair as a
 * generate (one batch, one undo step, the placement carried forward); Reject
 * and Save as new make ZERO scene changes. The candidate is already a
 * registered asset either way — the API persisted it when it generated it.
 */
function AdImageCandidateReview({
  candidate,
  disabled,
  imageAi,
  onClearInstruction,
}: {
  candidate: NonNullable<SceneImageAiBinding["candidate"]>;
  /** G-H (AD4.R-10): all three answers are operations — Accept and Save as new
   * write, and Reject discards a staged (paid) result — so all three are refused
   * while an agent turn is in flight. The comparison itself stays fully visible
   * and fully readable: it is a statement about what is on offer, and the ruling
   * gates operating, not looking. Reject and Save as new carry the accepted A19
   * residual noted at `AdImageAiRows` — inert, not dimmed. */
  disabled: boolean;
  imageAi: SceneImageAiBinding;
  /** Upstream clears the instruction on Accept and on Save as new, and not on
   * Reject (`ImageInspectorSection.tsx:159,178` vs `:165-168`) — because after
   * either of those the instruction has been ANSWERED, and leaving it in the box
   * puts a paid re-run of the edit that was just applied one click away. Reject
   * keeps it, which is the whole point of rejecting: try again, adjusted.
   *
   * CALLED ONLY WHEN THE ACTION LANDED. `onAccept` refuses silently over a
   * locked node, an unarmed engine or a CAS-refused batch, and those are exactly
   * the cases that KEEP the candidate for a retry — so clearing unconditionally
   * emptied a box the user had typed into for a write that never happened. This
   * lane's fifth discipline in its own small way: a refusal touches nothing. */
  onClearInstruction: () => void;
}) {
  return (
    <>
      <div className={styles.fieldGrid}>
        <AdImageReviewTile caption="Before" src={imageAi.beforeSrc} />
        <AdImageReviewTile caption="After" src={candidate.previewSrc} />
      </div>
      {/* TWO buttons in the two-up row and the third full width beneath it,
          rather than a three-column cram: `.fieldGrid` is a fixed
          `repeat(2, minmax(0, 1fr))`, and "Save as new" does not fit a third of
          a 248px column without truncating. */}
      <div className={styles.fieldGrid}>
        <button
          className={styles.sharePrimaryButtonWide}
          disabled={disabled}
          onClick={() => {
            if (imageAi.onAccept()) onClearInstruction();
          }}
          type="button"
        >
          Accept
        </button>
        <button
          className={styles.shareSecondaryButton}
          disabled={disabled}
          onClick={imageAi.onRejectCandidate}
          type="button"
        >
          Reject
        </button>
      </div>
      <button
        className={styles.shareSecondaryButton}
        disabled={disabled}
        onClick={() => {
          if (imageAi.onSaveCandidateAsNew()) onClearInstruction();
        }}
        type="button"
      >
        Save as new
      </button>
    </>
  );
}

/** One half of the comparison. `alt=""` on both: the caption beside the image
 * already names which half this is, and the pictures themselves are the
 * comparison — a screen reader reading a generated description here would
 * announce the very thing under review as though it were settled. */
function AdImageReviewTile({
  caption,
  src,
}: {
  caption: string;
  src: string | null;
}) {
  return (
    <div className={styles.imageReplaceField}>
      {src ? <Image alt="" fill sizes="124px" src={src} unoptimized /> : null}
      <span>{caption}</span>
    </div>
  );
}

function AdImageInspector({
  addressing,
  assetLibrary,
  hydrated,
  imageAi,
  inspectorDisabled = false,
  locked = false,
  onReplaceImage,
  onSelectionChange,
  ...binding
}: AdSchemaBinding & {
  assetLibrary?: SceneAssetLibraryBinding;
  imageAi?: SceneImageAiBinding;
  onReplaceImage?: (file: File) => void | Promise<void>;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
}) {
  const controller = useInspectorController(
    [],
    "image",
    hydrated ?? undefined,
    addressing,
    // AD4.R live hydration — see the text schema's controller.
    { liveHydration: hydrated != null },
  );
  const { setNestedValue, setValue, state, toggleSection } = controller;
  // G-H (AD4.R-10): this schema's two refusals in one expression — the node's
  // own lock (upstream's `disabled={selectedNode.locked}` posture) and the
  // in-flight agent turn. `RadiusControls` composes the same pair itself, so it
  // still takes them as the two separate facts they are (see its call below).
  const inert = locked || inspectorDisabled;
  // §1.3 row 2 (Alt text) — AD4.R-7: the `committed`/`draft`/`seen` TRIPLE that
  // stood here is retired. The box is now a self-drafting projection of
  // `state.altText`, which live hydration (Task 4) makes the document's own
  // text rather than a mount-time copy of it.
  //
  // Each of the triple's three jobs is now done by something else, or is gone:
  //
  //  • `draft`     — moved INSIDE the primitive. `onCommitValue` (Task 3) makes
  //                  `InspectorInput` hold its own edit-in-progress and hand
  //                  back the text on blur/Enter, so the schema never stores a
  //                  keystroke. The row still COMMITS ON BLUR/ENTER, never per
  //                  keystroke: a per-keystroke description would persist one
  //                  document version and one undo step per letter.
  //  • `committed` — deleted. It existed because the dirty check could not trust
  //                  the `values`-prop equivalent (ruling A27's premise). Under
  //                  live derivation the prop IS the document, so the check the
  //                  primitive runs compares against the document itself — one
  //                  fewer copy that can disagree with it.
  //  • `seen`      — deleted with the re-seed it guarded. The re-seed existed
  //                  for the SIBLING write (Replace image overwrites
  //                  `asset_placement.alt_text`, so a stale box would go on
  //                  describing the picture that just left). That is now free:
  //                  an unfocused box reads live state every render, and a
  //                  focused one has a draft the user is actively typing. The
  //                  mirror-timing hazard `seen` was written against died with
  //                  AD4.R-1's synchronous scene mirror.
  return (
    <>
      {/* §2 delta (contract row 7 / §5): the image "Link to" section is removed
          — an ad image carries no href. */}
      <Section id="fill" label="Fill" open={state.openSections.fill} toggle={() => toggleSection("fill")}>
        {/* §1.3 row 1 (AD4.A step 2): the file picker is REAL. `onFileSelect`
            used to be `requestAction("replace-image:…")`, which fires
            `clue:inspector-action` — an event nothing in the write path listens
            for — so a picked file swapped a local preview and changed nothing.
            The upload cannot live here (components may not import `data/` or
            the engine), so it arrives as a prop from the session; with no
            handler the dummy keeps its local-preview-only behaviour, never the
            old dead end.

            The preview `src` is the node's OWN asset (`scene-hydrate.ts`),
            falling back to the dummy's stock png. AD4.R-7: it reads
            `state.imagePreviewSrc` plainly, because under live hydration
            (Task 4) that IS the hydrated value — the controller no longer seeds
            a mount-time copy for the prop to have to out-rank. The special-case
            that read `hydrated` directly (review FIX 2, against the old
            seeded-once state) is therefore collapsed, not lost: a placement
            landing after a mid-upload reload still repaints the thumbnail,
            because `InspectorImageUpload` follows the live value when it
            changes. */}
        {/* Replace image, option A: with a live document behind it the pill is
            a two-row chooser (upload, or the workspace asset library); the
            dummy fixture path has no `assetLibrary`, so it keeps the direct
            file dialog it shipped with. */}
        <InspectorField label="Image"><InspectorImageUpload disabled={inert} onFileSelect={onReplaceImage} onOpenLibrary={assetLibrary?.open} src={state.imagePreviewSrc} /></InspectorField>
        <InspectorField label="Mode"><InspectorSelect disabled={inert} label="Image fill mode" onChange={(value) => setValue("fillMode", value)} options={FILL_MODES} value={state.fillMode} /></InspectorField>
        {/* §1.3 row 2 (AD4.A step 3): Alt text — the AI suite's one MANUAL
            row. Upstream has no alt-text generator, so this is an ordinary
            `asset_placement` write through the ordinary property seam, and it
            COMMITS ON BLUR/ENTER (`onCommitValue`), never per keystroke: a
            per-keystroke description would persist one document version and one
            undo step per letter. Upstream's own placeholder. */}
        <InspectorField label="Alt text">
          <InspectorInput
            ariaLabel="Image alt text"
            disabled={inert}
            // A29's surviving half: a locked node's commit skips the doomed
            // dispatch. Honesty no longer depends on it — nothing records
            // locally — it only spares the adapter a refusal.
            //
            // G-H (AD4.R-10) rides as its OWN line above it rather than
            // widening the condition: the A29 guard
            // (`scene-image-ai.test.ts`) pins `if (!locked) setValue("altText",
            // value);` verbatim as the proof a locked node records nothing, and
            // that pin is worth keeping literal. The field is natively disabled,
            // so this is the programmatic-blur backstop.
            onCommitValue={(value) => { if (inspectorDisabled) return; if (!locked) setValue("altText", value); }}
            placeholder="Describe the image"
            value={state.altText}
          />
        </InspectorField>
        {/* §1.3 row 2: the AI suite. Absent (the dummy fixture path, and any
            selection with no live scene behind it) the rows do not render at
            all, which is exactly what this schema shipped as. */}
        {imageAi ? <AdImageAiRows disabled={inert} imageAi={imageAi} /> : null}
      </Section>
      <Section id="shape" label="Shape" open={state.openSections.shape} toggle={() => toggleSection("shape")}>
        {/* A29: the lock rides in as data — a commit against a locked node
            records nothing, because §4 refused the write. G-H (AD4.R-10) sends
            the in-flight turn down BESIDE it, as the second, separate fact it
            is: `RadiusControls` composes the two itself (`disabled || locked`),
            so `inspectorDisabled` goes in here, never `inert`, or the lock would
            be counted twice and the primitive's own contract bypassed.
            `disabled` is deliberately out of alphabetical order and AFTER
            `locked`: the A29 guard (`scene-apply.test.ts`) pins
            `<RadiusControls locked={locked}` as a PREFIX — the proof this schema
            passes the header's LIVE lock — and that pin is worth more than the
            ordering convention. */}
        <InspectorField label="Radius"><RadiusControls locked={locked} disabled={inspectorDisabled} onChange={(corner, value) => setNestedValue("radius", corner, value)} values={state.radius} /></InspectorField>
      </Section>
      <Section id="layers" label="Layers" open={state.openSections.layers} toggle={() => toggleSection("layers")}>
        <AdLayers onSelectionChange={onSelectionChange} selected="image" {...binding} />
      </Section>
    </>
  );
}

// §2 delta (contract row 7 / §5): the button schema is hidden in v1 —
// `AdButtonInspector`, its `BUTTON_STYLE_OPTIONS`, its own "Link to" section
// and its padding controls are deleted. A `"button"` selection value survives
// in `model/chat-shell.ts` (dummy truth) and falls through to the default
// branch below until the model re-lift removes it.

export function ImageInspector({
  addressing,
  arrange,
  assetLibrary,
  error = null,
  fontOptions = DEFAULT_FONT_OPTIONS,
  hydrated,
  imageAi,
  inspectorDisabled = false,
  note = null,
  onReplaceImage,
  onSelectionChange,
  pageless = false,
  palette = null,
  selection,
  suppressAutoLayoutSection = false,
  ...layers
}: AdSchemaBinding & {
  /** §1.5 row (AD4.B step 4): the session's Arrange actions — z-order, the six
   * alignments, the two distributions and group/ungroup — plus what each may do
   * for the current selection. It goes to the schemas that RENDER an Arrange
   * section (the text schema and the four co-founder ones); absent, on the
   * dummy fixture path, leaves every one of those buttons exactly as it
   * shipped. */
  arrange?: SceneArrangeBinding;
  /** Replace image, option A: the session's asset-library picker. Only the
   * image schema reads it, and only `open` — the panel's job here is to OFFER
   * the library as the pill's second source; the picker itself is the session's
   * surface. Absent (the dummy fixture path) leaves "Replace image" the plain
   * file-dialog button it shipped as. */
  assetLibrary?: SceneAssetLibraryBinding;
  /** AD2.7: an inline write error. Same one-line floor the web branch renders
   * (the W3.3 founder gate forbids any new failure UI). */
  error?: string | null;
  /** §2 delta (contract row 3): the real font vocabulary, prop-fed. Absent
   * keeps the one safe default until AD2.4's hydration supplies the kit's. */
  fontOptions?: readonly string[];
  /** §1.3 row 2 (AD4.A step 3): the session's AI image suite — what the four
   * flows are showing and the six callbacks they commit through. Absent (the
   * dummy fixture path) renders no AI rows at all. */
  imageAi?: SceneImageAiBinding;
  /** AD4.R-10 / GATE G-H: the panel's write controls are closed because an agent
   * turn is in flight (see `AdHydrationBinding` for the ruling and the
   * operations-only scope).
   *
   * THE CHATS ROUTE PASSES IT; THE ARTIFACT ROUTE DOES NOT, and absent is
   * `false` — today's behaviour, byte for byte, on that route and on the dummy
   * fixture path. That asymmetry is deliberate and recorded: the in-flight
   * signal is the chat controller's `threadBusy`, and the artifact route has no
   * live turn stream to read it from. Its net there stays the D10 CAS
   * reconciliation (refuse-then-reload after the fact, proven at T8); a
   * DOCUMENT-scoped agent-busy signal — plausibly off the run_event SSE — is the
   * recorded follow-up that would close it. */
  inspectorDisabled?: boolean;
  /** AD2.7: a transient informational note (the 409 quiet reload). */
  note?: string | null;
  /** genad2 Task 5: the open document has NO page yet — `open_design_leg@4`
   * births a scene document with `pages: {}` and the design agent authors the
   * first page in a later turn. The canvas schema refuses its page rows for that
   * window rather than showing the fixture seeds over a document that measures
   * nothing. Absent is `false`: the dummy fixture path and every page-bearing
   * document behave exactly as they do today. */
  pageless?: boolean;
  /** §1.3 row 1 (AD4.A step 2): the session's Replace-image flow — upload the
   * picked file, then place it in the selected node. Absent (the dummy fixture
   * path) keeps the control's local-preview-only behaviour. A rejection means
   * the document did not take the file, and the control puts its preview back;
   * anything the user should read about is already in `error`. */
  onReplaceImage?: (file: File) => void | Promise<void>;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  /** AD4.0 step 3 (§1.6): the document's brand-kit colour palette, offered by
   * every colour picker in the panel. Absent keeps the dummy's own fixture
   * palette and disables the token write path entirely. */
  palette?: ScenePalette | null;
  selection: ChatShellInspectorSelection;
  /** AD2.4/OQ-1: a plain Frame renders the auto-layout schema WITHOUT its Auto
   * Layout section — the frame has no auto layout to state. */
  suppressAutoLayoutSection?: boolean;
}) {
  const headerController = useInspectorController(
    [],
    selection,
    hydrated ?? undefined,
    addressing,
    // AD4.R live hydration — see the text schema's controller.
    { liveHydration: hydrated != null },
  );
  // AD4.B step 1: the four co-founder schemas are no longer static, so this
  // decides only WHICH component renders — not, as it used to, whether the
  // node's lock is real. See the `schema` object below.
  const dummySelection = isAdDummyInspectorSelection(selection);
  // §1.0: the real node's own name when there is one; the dummy's fixture
  // titles ("Text34") only while nothing is hydrated.
  const title = hydrated?.title ?? AD_INSPECTOR_TITLES[selection] ?? "Canvas";
  // AD4.B step 1: ALL SEVEN schemas now take the same binding. The four
  // co-founder schemas (auto-layout / rectangle / ellipse / group, plus OQ-1's
  // plain Frame) used to be static scaffolding with no state fields to take a
  // hydrated value — ruling 14 — so they were handed the layer binding and the
  // header's title and nothing else. Ruling 14 is settled (the Layout keys live
  // in `InspectorPresentationState`), so `{...schema}` goes to them too.
  //
  // RULING A29: `locked` rides down as data, from the HEADER's controller
  // rather than each schema's own. The lock button writes through
  // `headerController` (below), so taking the value from there keeps ONE
  // statement of the lock for every schema — the controller that dispatches
  // the write is the one that reports the result.
  //
  // The original reason was sharper: a schema's own `state.locked` was a
  // mount-time seed, and a successful lock write deliberately does not remount
  // the panel (§4 / the AD3.2 keying rule), so it still said `false` a click
  // after the user locked the node. AD4.R-4 retired that half — every ad
  // schema's `state.locked` is live-derived from the accepted scene now — and
  // the routing stays for the single-source reason.
  //
  // AD4.B step 1 removed the dummy-selection ternary that used to force this
  // line — and the header's own lock below — to a hard `false` for the four
  // co-founder schemas. It was honest while those schemas had no
  // bound control and no controller to write a lock through: reporting `false`
  // kept an inoperable lock button off a panel that could not have used it. Now
  // that their Layout rows write, `false` would be the panel LYING about a
  // locked node — every one of those rows is gated on the very lock it was
  // hiding, so the user would type into live-looking boxes that the adapter
  // silently refuses (§4). The old literal is pinned negatively by RULING A29's
  // guard in `scene-apply.test.ts` so it cannot return.
  const schema = {
    addressing,
    hydrated,
    inspectorDisabled,
    locked: headerController.state.locked,
    onSelectionChange,
    ...layers,
  };

  return (
    <ScenePaletteContext.Provider value={palette}>
      <aside aria-label="Ad inspector" className={styles.inspector}>
        <div className={styles.inspectorRail}>
          {/* §2 delta (contract row 7): no `onVisibilityToggle` is passed, so the
              header renders no eye on any ad schema. */}
          <InspectorHeader
            // G-H (AD4.R-10): `inspectorDisabled` ALONE, never the node lock —
            // locking is the one operation whose own outcome this button states,
            // so a locked node must keep an enabled way back out.
            disabled={inspectorDisabled}
            elementActions={selection !== "canvas" && selection !== "button"}
            locked={headerController.state.locked}
            onLockToggle={() => headerController.setValue("locked", !headerController.state.locked)}
            title={title}
          />
          {/* The web branch's own inline slot, verbatim: note (409 quiet reload)
              then error (a refused edit / transport failure). */}
          {note ? (
            <p className={styles.inspectorStatusNote} role="status">
              {note}
            </p>
          ) : null}
          {error ? (
            <p className={styles.inspectorStatusError} role="alert">
              {error}
            </p>
          ) : null}
          {selection === "canvas" ? <AdCanvasInspector pageless={pageless} {...schema} /> : null}
          {selection === "text" ? <AdTextInspector arrange={arrange} fontOptions={fontOptions} {...schema} /> : null}
          {/* `onReplaceImage`, `imageAi` and `assetLibrary` go to THIS schema
              alone — the rows are §1.3's — the way `fontOptions` goes only to
              the text schema. */}
          {selection === "image" ? <AdImageInspector assetLibrary={assetLibrary} imageAi={imageAi} onReplaceImage={onReplaceImage} {...schema} /> : null}
          {dummySelection ? <AdDummyInspector arrange={arrange} selection={selection} suppressAutoLayoutSection={suppressAutoLayoutSection} {...schema} /> : null}
          {/* `"button"` is deliberately absent from this list: with its schema
              hidden (row 7) it falls through to the canvas default. */}
          {!(["auto-layout", "canvas", "ellipse", "group", "image", "rectangle", "text"] as ChatShellInspectorSelection[]).includes(selection) ? <AdCanvasInspector pageless={pageless} {...schema} /> : null}
        </div>
      </aside>
    </ScenePaletteContext.Provider>
  );
}
