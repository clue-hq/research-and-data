"use client";

import Image from "next/image";
import { createContext, useContext, useState, type ReactNode } from "react";
import {
  backgroundFillCommits,
  customSizeForPreset,
  mintedStrokeColor,
  mintedStrokeWidth,
  type SceneInspectorState,
} from "@/features/design-editor/adapter/scene-hydrate";
import type { SceneImageAiBinding } from "@/features/design-editor/adapter/scene-image-ai";
import {
  scenePaletteColor,
  type ScenePalette,
} from "@/features/design-editor/adapter/scene-palette";
import type { ThemeColorOption } from "@/features/design-editor/adapter/theme-options";
import type { ChatShellInspectorSelection } from "../model/chat-shell";
import {
  useInspectorController,
  useInspectorLayerTree,
  type HorizontalAlignment,
  type InspectorBackgroundFill,
  type InspectorEventAddressing,
} from "../hooks/use-inspector-controller";
import {
  BackgroundFillControl,
  ColorControl,
  InspectorField,
  InspectorHeader,
  InspectorIcon,
  InspectorImageUpload,
  InspectorInput,
  InspectorLayerRow,
  InspectorSection,
  InspectorSelect,
  RadiusControls,
} from "./inspector-primitives";
import styles from "./chat-shell.module.css";
import {
  AdDummyInspector,
  AdSceneLayers,
  isAdDummyInspectorSelection,
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

/**
 * AD4.0 step 3 (§1.6): the document's brand palette for every ColorControl in
 * this panel, carried as data — the seam rule, presentation never fetches.
 *
 * A CONTEXT rather than a prop drilled through each schema, copying the
 * website lane's `ThemeColorsContext` (`web-inspector.tsx`) for the same
 * reason it exists there: the four schemas Lane B is about to bind then
 * inherit the feed without touching this file again. `null` — the chats route
 * before a document loads, a document with no attached kit, a kit fetch that
 * failed — leaves every picker on the dummy's own palette, unchanged.
 */
const ScenePaletteContext = createContext<ScenePalette | null>(null);

/** The palette itself, for the rows that must RESOLVE a token (§1.6/R3b). */
function useScenePalette() {
  return useContext(ScenePaletteContext);
}

/**
 * What the pickers are OFFERED, or `undefined` when this document has no brand
 * swatches to offer — which is also the signal that no token write may fire.
 *
 * The two are one question deliberately: with no options, `ColorControl` falls
 * back to `INSPECTOR_THEME_COLORS` (the dummy's fixture palette), and a pick
 * from THAT list names no token this document has. Passing `onTokenChange`
 * alongside it would write `{kind:"token", token:"Primary"}` — a binding
 * nothing can resolve. So callers below gate the token handler on this exact
 * value, and `scene-apply.ts` refuses the label a second time at the write.
 */
function useScenePaletteOptions() {
  const palette = useScenePalette();
  return palette && palette.options.length > 0 ? palette.options : undefined;
}

/**
 * §1.6: ONE colour row — what its swatch is showing, and the two handlers its
 * two halves commit through. Every ad colour control goes through it, so the
 * brand and custom paths cannot drift apart three times over.
 *
 * WHY IT HOLDS A LOCAL DRAFT. The controller's `token*` field is the WRITE
 * channel, and a brand pick sets only that — `textColor` deliberately stays
 * where it was, because `setValue` IS the dispatch and updating it too would
 * fire a second, spurious hex write for one click (the same rule step 1 gave
 * for the Custom W/H boxes). But the swatch reads its value from a PROP, so
 * with nothing tracking the pick the trigger kept showing the previous colour
 * while the artboard repainted with the new one — a panel stating a colour the
 * document no longer has, which is the defect step 1 and step 2 each closed
 * once already. This draft is what the row has shown since it mounted.
 *
 * WHICH VALUE WINS is "whichever was set last", because that is the fact the
 * panel must state: a brand pick shows the token, and the custom hex that
 * DETACHES it (§1.6's informed trade) clears the draft and shows the hex.
 * With no pick yet, the hydrated value stands — which for a token-bound node
 * is the token's own name.
 *
 * R3b: `color` then RESOLVES that value through the palette, because a token
 * name is not a CSS colour — the chip painted nothing, the Custom tab's picker
 * opened on black, and the picker could not mark the bound swatch as pressed.
 * The name still stands when the palette cannot resolve it (no kit attached,
 * an off-catalog token), which is step 2's truthful display, unchanged.
 */
function useAdColorRow({
  hydratedValue,
  onHex,
  onToken,
  paletteOptions,
}: {
  hydratedValue: string;
  onHex: (hex: string) => void;
  onToken: (label: string) => void;
  paletteOptions: readonly ThemeColorOption[] | undefined;
}) {
  const palette = useScenePalette();
  const [shown, setShown] = useState("");
  /** The swatch value this row is showing — a token name or a colour. */
  const value = shown === "" ? hydratedValue : shown;
  return {
    color: scenePaletteColor(palette, value) ?? value,
    onColorChange: (hex: string) => {
      setShown(hex);
      onHex(hex);
    },
    // Absent options mean the picker is showing the DUMMY's fixture palette,
    // whose labels name no token this document has — so no token handler is
    // offered at all (under A23 that tab is empty, so there is nothing to pick
    // either), and the Custom tab commits its hex as it always has.
    onTokenChange: paletteOptions && ((label: string) => {
      setShown(label);
      onToken(label);
    }),
    /** A9: a SIBLING control's write can change what this row must show — a
     * width typed on a strokeless node mints a colour. This is how that
     * sibling states it, without a dispatch of its own. */
    setShown,
    value,
  };
}

/**
 * AD2.7: what a caller supplies to drive the ad inspector from a REAL scene
 * node — the web branch's own prop set (`WebInspector`'s `hydrated` +
 * `addressing` + `error`/`note`), ad-side.
 *
 * Every field is optional and absent means "the dummy as it shipped", so the
 * fixture path keeps compiling and keeps rendering (the AD0.4 `fontOptions?`
 * precedent, extended). `hydrated` carries AD2.4's extra fields too
 * (`title`, `opacity`, the size modes — ruling 14); only the ones with a state
 * field reach a control today, and the rest ride along for AD4.B.
 */
interface AdHydrationBinding {
  /** Write addressing stamped onto every inspector event this panel raises.
   * Its `documentVersion` is null until AD3 wires the scene write path — the
   * W3.1 null contract, i.e. "not addressable", i.e. no write can fire. */
  addressing?: InspectorEventAddressing;
  /** RULING A29: the selected node's LIVE lock (the header controller's, not a
   * schema's mount-time seed), for the controls whose local state must not
   * record a write §4 refuses. */
  locked?: boolean;
  /** The selected node's real values (or the page's, for the canvas schema),
   * merged over the dummy defaults at mount. Initial state only: the caller
   * remounts this panel per selection (`key={primaryNodeId ?? "canvas"}`), the
   * same discipline the web branch uses. */
  hydrated?: SceneInspectorState | null;
}

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
  horizontal,
  onHorizontalChange,
  onVerticalChange,
  vertical,
}: {
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
      <div aria-label="Horizontal alignment" className={`${styles.alignmentControl} ${styles.alignmentControlQuad}`} role="group">
        {horizontalOptions.map(([value, icon]) => (
          <button aria-label={`Align ${value}`} aria-pressed={horizontal === value} className={horizontal === value ? styles.alignmentActive : ""} key={value} onClick={() => onHorizontalChange(value)} type="button">
            <InspectorIcon name={icon} size={12} />
          </button>
        ))}
      </div>
      <div aria-label="Vertical alignment" className={`${styles.alignmentControl} ${styles.verticalAlignment}`} role="group">
        {verticalOptions.map(([value, icon]) => (
          <button aria-label={`Align ${value}`} aria-pressed={vertical === value} className={vertical === value ? styles.alignmentActive : ""} key={value} onClick={() => onVerticalChange(value)} type="button">
            <InspectorIcon name={icon} size={12} />
          </button>
        ))}
      </div>
    </div>
  );
}

function ArrangeControls({ onAction }: { onAction: (action: string) => void }) {
  const layerActions = [
    ["Bring to front", "align-top"],
    ["Bring forward", "align-middle"],
    ["Send backward", "align-center"],
    ["Send to back", "align-bottom"],
  ] as const;
  const alignmentActions = [
    ["Align left", "align-left"],
    ["Align center", "align-center"],
    ["Align right", "align-right"],
    ["Align top", "align-top"],
    ["Align middle", "align-middle"],
    ["Align bottom", "align-bottom"],
  ] as const;

  return (
    <>
      <InspectorField label="Layer">
        <div className={`${styles.inspectorActionGrid} ${styles.inspectorActionGridFour}`}>
          {layerActions.map(([label, icon]) => (
            <button aria-label={label} key={label} onClick={() => onAction(label)} type="button"><InspectorIcon name={icon} size={12} /></button>
          ))}
        </div>
      </InspectorField>
      <InspectorField label="Alignment">
        <div className={`${styles.inspectorActionGrid} ${styles.inspectorActionGridSix}`}>
          {alignmentActions.map(([label, icon]) => (
            <button aria-label={label} key={label} onClick={() => onAction(label)} type="button"><InspectorIcon name={icon} size={12} /></button>
          ))}
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
  fontOptions,
  hydrated,
  onSelectionChange,
  ...binding
}: AdSchemaBinding & {
  fontOptions: readonly string[];
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
}) {
  // The shared dummy default ("Semi Bold") is not one of the §2-row-2 named
  // weights, so this schema opens on the matching nine-name value. The web
  // inspector keeps its own four-name list and the untouched shared default.
  // A hydrated weight is a real one and wins; a node whose weight is off the
  // nine-name ramp hydrates none (AD2.4) and keeps this default.
  const initial = { fontWeight: "600 Semi Bold", ...hydrated };
  const controller = useInspectorController([], "text", initial, addressing);
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
  // RULING A9 makes this row's two fields move TOGETHER, so each half re-seeds
  // the other's display — the sibling rule step 1 settled for the Custom W/H
  // boxes (`customSizeForPreset`), applied to the row A9 has just made live on
  // strokeless nodes. Both decisions are the adapter's (`mintedStrokeWidth` /
  // `mintedStrokeColor`), never restated here, and both re-seed LOCAL state:
  // routing them through `setValue` would fire a second, spurious write for
  // one user action.
  const [strokeWidth, setStrokeWidth] = useState(state.strokeWidth);
  // Reads `strokeRow.value` BEFORE committing: the question is what the row was
  // showing when the write decided, which is the same fact the write read off
  // the node. (`strokeRow` is declared just below — these run at event time,
  // long after it is bound.)
  const commitStrokeColor = (commit: () => void) => {
    const minted = mintedStrokeWidth(strokeRow.value);
    commit();
    if (minted !== null) setStrokeWidth(minted);
  };
  const strokeRow = useAdColorRow({
    hydratedValue: state.strokeColor,
    onHex: (hex) => commitStrokeColor(() => setValue("strokeColor", hex)),
    onToken: (label) =>
      commitStrokeColor(() => setValue("tokenStrokeColor", label)),
    paletteOptions,
  });
  const changeStrokeWidth = (value: string) => {
    setStrokeWidth(value);
    setValue("strokeWidth", value);
    // A9's mirror: a width on a node with no stroke mints upstream's default
    // colour, so the swatch beside it must stop saying none.
    const minted = mintedStrokeColor(strokeRow.value, value);
    if (minted !== null) strokeRow.setShown(minted);
  };

  return (
    <>
      <Section id="typography" label="Typography" open={state.openSections.typography} toggle={() => toggleSection("typography")}>
        <InspectorField label="Color"><ColorControl color={colorRow.color} fixtureFallback={false} onColorChange={colorRow.onColorChange} onTokenChange={colorRow.onTokenChange} options={paletteOptions} /></InspectorField>
        <InspectorField label="Font"><InspectorSelect label="Font family" onChange={(value) => setValue("fontFamily", value)} options={fontOptions} value={state.fontFamily} /></InspectorField>
        <div className={styles.fieldGrid}>
          {/* §2 delta (contract row 2): the size select becomes a free number. */}
          <InspectorField label="Size"><InspectorInput ariaLabel="Font size" onChange={(value) => setValue("fontSize", value)} value={state.fontSize} /></InspectorField>
          <InspectorField label="Weight"><InspectorSelect label="Font weight" onChange={(value) => setValue("fontWeight", value)} options={FONT_WEIGHT_OPTIONS} value={state.fontWeight} /></InspectorField>
        </div>
        <InspectorField label="Alignment"><TextAlignment horizontal={state.horizontalAlignment} onHorizontalChange={(value) => setValue("horizontalAlignment", value)} onVerticalChange={(value) => setValue("verticalAlignment", value)} vertical={state.verticalAlignment} /></InspectorField>
      </Section>
      <Section id="stroke" label="Stroke" open={state.openSections.stroke} toggle={() => toggleSection("stroke")}>
        <InspectorField label="Color"><ColorControl color={strokeRow.color} fixtureFallback={false} onColorChange={strokeRow.onColorChange} onTokenChange={strokeRow.onTokenChange} options={paletteOptions} /></InspectorField>
        <InspectorField label="Width"><InspectorInput ariaLabel="Stroke width" onChange={changeStrokeWidth} value={strokeWidth} /></InspectorField>
      </Section>
      <Section id="layout" label="Layout" open={state.openSections.layout} toggle={() => toggleSection("layout")}>
        <InspectorField label="Position">
          <div className={styles.fieldGrid}>
            <InspectorInput ariaLabel="X position" onChange={(value) => setNestedValue("position", "x", value)} prefix="X" value={state.position.x} />
            <InspectorInput ariaLabel="Y position" onChange={(value) => setNestedValue("position", "y", value)} prefix="Y" value={state.position.y} />
          </div>
        </InspectorField>
        <InspectorField label="Rotation"><InspectorInput ariaLabel="Rotation" onChange={(value) => setValue("rotation", value)} suffix="°" value={state.rotation} /></InspectorField>
      </Section>
      <Section id="arrange" label="Arrange" open={state.openSections.arrange} toggle={() => toggleSection("arrange")}>
        <ArrangeControls onAction={(action) => requestAction(`arrange:${action}`)} />
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
  onSelectionChange,
  ...binding
}: AdSchemaBinding & {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
}) {
  // Pin the select to its own option list: the shared DEFAULT_STATE carries the
  // same corrected §2.1 string today, but this override keeps the schema's value
  // coupled to SIZE_PRESETS so a relabel can never orphan the <select>. A real
  // page hydrates its own preset (or "Custom") over it.
  const initial = { sizePreset: SIZE_PRESETS[0], ...hydrated };
  const controller = useInspectorController([], "canvas", initial, addressing);
  const { setValue, state, toggleSection } = controller;
  const palette = useScenePalette();
  const paletteOptions = useScenePaletteOptions();
  // §1.6: the Background section's colour row, through the same hook the text
  // and stroke rows use. Its `color` is what the solid swatch AND the gradient
  // preview are drawn from (a token name is not a CSS colour, so a
  // token-filled frame previewed as nothing), and its `value` is the raw
  // swatch value a mode switch re-seeds from.
  const backgroundRow = useAdColorRow({
    hydratedValue: state.backgroundColor,
    onHex: (hex) => setValue("backgroundColor", hex),
    onToken: (label) => setValue("tokenBackgroundColor", label),
    paletteOptions,
  });
  // §2 delta (contract row 1): Custom reveals W/H (px only). AD4.0 binds the
  // pair to the write seam — they were the last designed ad control still
  // holding draft state and dispatching nothing at all.
  //
  // They COMMIT ON BLUR/ENTER, not per keystroke (`InspectorInput`'s opt-in
  // `onCommit`, the W4.2 ratified commit model). This is upstream parity, not
  // a local preference: the standalone editor's own page W/H fields are
  // `NumberField`s committing the same way (`DocumentPageSection.tsx:105-118`).
  // Per keystroke, typing "108" persisted THREE document versions and left the
  // page at 108px wide — proven in the browser at review — so one digit typed
  // before switching tabs would durably resize the ad to 1px. The draft below
  // is what the user sees while typing; only the commit reaches the seam.
  // (§1.2's Size box keeps its per-keystroke behaviour: a font size is not a
  // page resize, and changing it is not this step's row.)
  //
  // The pair keeps BOTH the typed draft and the value last committed, because
  // the second is what decides whether a blur is a write at all — and both must
  // move when the SELECT beside them resizes the page. A successful write does
  // not remount the inspector (§4 / the AD3.2 keying rule), so nothing else
  // would: the boxes kept their mount-time seed and offered a size the document
  // no longer had (proven in the browser: Custom 1100x1600 → pick the LinkedIn
  // square → re-open Custom → still 1100/1600 against a 1200x1200 page). The
  // re-seed is deliberately narrow — only the preset rows, the only writes that
  // can resize the page today — and is NOT a general re-hydrate-on-write
  // mechanism, which would fight §4.
  //
  // It re-seeds this local state rather than the controller's, because
  // `setValue` IS the dispatch: routing the re-seed through it would fire a
  // second, spurious `customWidth`/`customHeight` write for one user action.
  // The controller's own fields stay what they are — the mount-time hydration
  // seed these two are born from.
  const [custom, setCustom] = useState(() => {
    const seed = { height: state.customHeight, width: state.customWidth };
    return { committed: seed, draft: seed };
  });
  const draftCustomSize = (axis: "height" | "width", value: string) =>
    setCustom((current) => ({
      ...current,
      draft: { ...current.draft, [axis]: value },
    }));
  const commitCustomSize = (axis: "height" | "width") => {
    // Read from this render's state and dispatch OUTSIDE the updater — a
    // `setValue` inside one would be a side effect React is free to run twice.
    const value = custom.draft[axis];
    if (value === custom.committed[axis]) return;
    setValue(axis === "width" ? "customWidth" : "customHeight", value);
    setCustom((current) => ({
      ...current,
      committed: { ...current.committed, [axis]: value },
    }));
  };
  // §1.1 row 2 / Ruling A15.2: the Background fill control's one handler. The
  // DECISION is pure and lives in the adapter (`backgroundFillCommits`, which
  // states the two browser-proven defects it fixes); this is only the dispatch,
  // exactly as `changeSizePreset` below is only the dispatch plus its re-seed.
  //
  // A mode switch to Solid returns TWO commits — the type (so the control
  // renders the swatch) and the colour (the row that actually carries one) —
  // and they collapse to ONE document version, because a solid fill object maps
  // to no operation by contract. This is not a general re-hydrate mechanism: it
  // is this section's own handler keeping its two controls consistent with the
  // writes it dispatches.
  //
  // R3b (step 3): the re-seed reads `backgroundRow.value` — the value the
  // swatch is showing RIGHT NOW, including a brand token picked since mount,
  // which `state.backgroundColor` does not carry (a token pick writes the
  // `token*` field, by design). Seeding from the controller's field instead
  // would re-introduce A15.2's own stale-seed defect one edit later.
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
        // Through the ROW's own handler, not `setValue` directly: it is a
        // colour landing on this swatch, so it must also clear any brand token
        // picked since mount — or the swatch would go on showing a binding the
        // switch just replaced.
        backgroundRow.onColorChange(commit.value);
      } else {
        setValue("backgroundFill", commit.value);
      }
    }
  };
  const changeSizePreset = (label: string) => {
    setValue("sizePreset", label);
    // The picked preset IS the page's new size, so the boxes read it — "Custom"
    // and any unoffered label resize nothing and re-seed nothing.
    const resized = customSizeForPreset(label);
    if (resized) setCustom({ committed: resized, draft: resized });
  };
  return (
    <>
      <Section id="dimensions" label="Dimensions" open={state.openSections.dimensions} toggle={() => toggleSection("dimensions")}>
        <InspectorField label="Size"><InspectorSelect label="Canvas dimensions" onChange={changeSizePreset} options={SIZE_PRESETS} value={state.sizePreset} /></InspectorField>
        {state.sizePreset === "Custom" ? (
          <InspectorField label="Custom size">
            <div className={styles.fieldGrid}>
              <InspectorInput ariaLabel="Custom width" onChange={(value) => draftCustomSize("width", value)} onCommit={() => commitCustomSize("width")} prefix="W" value={custom.draft.width} />
              <InspectorInput ariaLabel="Custom height" onChange={(value) => draftCustomSize("height", value)} onCommit={() => commitCustomSize("height")} prefix="H" value={custom.draft.height} />
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
            fill={state.backgroundFill}
            fixtureFallback={false}
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
function AdImageAiRows({ imageAi }: { imageAi: SceneImageAiBinding }) {
  const [prompt, setPrompt] = useState("");
  const [instruction, setInstruction] = useState("");
  const { candidate, canEdit, editing, generating, hasImage, savedNotice, statusLine } =
    imageAi;
  return (
    <>
      <InspectorField label={hasImage ? "Regenerate" : "Generate image"}>
        <InspectorInput
          ariaLabel="Image prompt"
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
        disabled={generating || prompt.trim() === ""}
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
                disabled={instruction.trim() === ""}
                onClick={() => imageAi.onEdit(instruction)}
                type="button"
              >
                Edit
              </button>
              <button
                className={styles.shareSecondaryButton}
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
  imageAi,
  onClearInstruction,
}: {
  candidate: NonNullable<SceneImageAiBinding["candidate"]>;
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
          onClick={() => {
            if (imageAi.onAccept()) onClearInstruction();
          }}
          type="button"
        >
          Accept
        </button>
        <button
          className={styles.shareSecondaryButton}
          onClick={imageAi.onRejectCandidate}
          type="button"
        >
          Reject
        </button>
      </div>
      <button
        className={styles.shareSecondaryButton}
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
  hydrated,
  imageAi,
  locked = false,
  onReplaceImage,
  onSelectionChange,
  ...binding
}: AdSchemaBinding & {
  imageAi?: SceneImageAiBinding;
  onReplaceImage?: (file: File) => void | Promise<void>;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
}) {
  const controller = useInspectorController(
    [],
    "image",
    hydrated ?? undefined,
    addressing,
  );
  const { setNestedValue, setValue, state, toggleSection } = controller;
  // §1.3 row 2 (Alt text): THREE values in one state object, so they cannot
  // drift — the `RadiusControls` `committed`/`draft` shape (ruling A27), with
  // one field it does not need.
  //
  //  • `draft`     — what the box is showing.
  //  • `committed` — what this panel believes the document holds. The dirty
  //                  check reads THIS and never the live prop, which is
  //                  `RadiusControls`' own discipline (`inspector-primitives.tsx`,
  //                  ruling A27) and the reason the field exists.
  //  • `seen`      — the last hydrated value this component reacted to. It is
  //                  what makes the re-seed below fire on a SIBLING write and
  //                  not on our own.
  //
  // THE RE-SEED IS WHY THE PROP IS READ AT ALL. Replace image overwrites
  // `asset_placement.alt_text`, so without it the box would go on describing
  // the picture that just left. React's adjust-state-on-prop-change (a
  // render-time comparison, never an effect, which would render one stale frame
  // and is barred by this repo's lint), the technique step 2's review used for
  // the Fill thumbnail.
  //
  // AND `seen` IS WHY IT DOES NOT SNAP BACK. The optimistic apply mirrors up
  // through a passive effect, so for a render or two after a commit the live
  // prop still holds the PRE-write text. Comparing the re-seed against
  // `committed` (which the commit just moved) would fire it against that stale
  // value and flash the old description; comparing against `seen` — which only
  // a genuinely new prop moves — does not.
  const documentAltText = hydrated?.altText ?? state.altText;
  const [altText, setAltText] = useState(() => ({
    committed: documentAltText,
    draft: documentAltText,
    seen: documentAltText,
  }));
  if (altText.seen !== documentAltText) {
    setAltText({
      committed: documentAltText,
      draft: documentAltText,
      seen: documentAltText,
    });
  }
  const commitAltText = () => {
    // A29: a commit against a LOCKED node records nothing, because §4 refuses
    // the write — the box keeps what was typed (the ratified A19 posture) and
    // the panel's record of the document does not move.
    if (locked) return;
    // A write that changes nothing is not a write. The comparison is against
    // what this panel believes the document holds, which is also exactly what
    // the adapter compares (`effectiveAltText`), so the two can never disagree
    // about what "changed".
    if (altText.draft !== altText.committed) setValue("altText", altText.draft);
    setAltText((current) => ({ ...current, committed: current.draft }));
  };
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
            falling back to the dummy's stock png. It reads the LIVE `hydrated`
            prop rather than `state.imagePreviewSrc`, which the controller seeds
            once at mount: a placement that lands after a mid-upload reload has
            already remounted this panel would otherwise leave the thumbnail on
            the previous asset while the artboard repainted with the new one
            (review FIX 2). `InspectorImageUpload` follows the value when it
            changes. */}
        <InspectorField label="Image"><InspectorImageUpload onFileSelect={onReplaceImage} src={hydrated?.imagePreviewSrc ?? state.imagePreviewSrc} /></InspectorField>
        <InspectorField label="Mode"><InspectorSelect label="Image fill mode" onChange={(value) => setValue("fillMode", value)} options={FILL_MODES} value={state.fillMode} /></InspectorField>
        {/* §1.3 row 2 (AD4.A step 3): Alt text — the AI suite's one MANUAL
            row. Upstream has no alt-text generator, so this is an ordinary
            `asset_placement` write through the ordinary property seam, and it
            COMMITS ON BLUR/ENTER (`onCommit`), never per keystroke: a
            per-keystroke description would persist one document version and one
            undo step per letter. Upstream's own placeholder. */}
        <InspectorField label="Alt text">
          <InspectorInput
            ariaLabel="Image alt text"
            onChange={(value) => setAltText((current) => ({ ...current, draft: value }))}
            onCommit={commitAltText}
            placeholder="Describe the image"
            value={altText.draft}
          />
        </InspectorField>
        {/* §1.3 row 2: the AI suite. Absent (the dummy fixture path, and any
            selection with no live scene behind it) the rows do not render at
            all, which is exactly what this schema shipped as. */}
        {imageAi ? <AdImageAiRows imageAi={imageAi} /> : null}
      </Section>
      <Section id="shape" label="Shape" open={state.openSections.shape} toggle={() => toggleSection("shape")}>
        {/* A29: the lock rides in as data — a commit against a locked node
            records nothing, because §4 refused the write. */}
        <InspectorField label="Radius"><RadiusControls locked={locked} onChange={(corner, value) => setNestedValue("radius", corner, value)} values={state.radius} /></InspectorField>
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
  error = null,
  fontOptions = DEFAULT_FONT_OPTIONS,
  hydrated,
  imageAi,
  note = null,
  onReplaceImage,
  onSelectionChange,
  palette = null,
  selection,
  suppressAutoLayoutSection = false,
  ...layers
}: AdSchemaBinding & {
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
  /** AD2.7: a transient informational note (the 409 quiet reload). */
  note?: string | null;
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
  );
  const dummySelection = isAdDummyInspectorSelection(selection);
  // §1.0: the real node's own name when there is one; the dummy's fixture
  // titles ("Text34") only while nothing is hydrated.
  const title = hydrated?.title ?? AD_INSPECTOR_TITLES[selection] ?? "Canvas";
  // The three schemas AD0.1 authored as live controllers take the hydrated
  // values; the four static ones (auto-layout / rectangle / ellipse / group)
  // have no state fields to take them — ruling 14, AD4.B's to bind — so they
  // get the layer binding and the header's real title, and nothing else.
  //
  // RULING A29: `locked` rides down as data, from the HEADER's controller
  // rather than each schema's own. The lock button writes through
  // `headerController` (below), and a successful write deliberately does not
  // remount the panel (§4 / the AD3.2 keying rule) — so a schema's own
  // `state.locked`, seeded once at mount, would still say `false` a click after
  // the user locked the node, which is exactly when a control must stop
  // recording writes the adapter is refusing.
  const schema = {
    addressing,
    hydrated,
    locked: dummySelection ? false : headerController.state.locked,
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
            elementActions={selection !== "canvas" && selection !== "button"}
            locked={dummySelection ? false : headerController.state.locked}
            onLockToggle={dummySelection ? undefined : () => headerController.setValue("locked", !headerController.state.locked)}
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
          {selection === "canvas" ? <AdCanvasInspector {...schema} /> : null}
          {selection === "text" ? <AdTextInspector fontOptions={fontOptions} {...schema} /> : null}
          {/* `onReplaceImage` and `imageAi` go to THIS schema alone — the rows
              are §1.3's — the way `fontOptions` goes only to the text schema. */}
          {selection === "image" ? <AdImageInspector imageAi={imageAi} onReplaceImage={onReplaceImage} {...schema} /> : null}
          {dummySelection ? <AdDummyInspector onSelectionChange={onSelectionChange} selection={selection} suppressAutoLayoutSection={suppressAutoLayoutSection} {...layers} /> : null}
          {/* `"button"` is deliberately absent from this list: with its schema
              hidden (row 7) it falls through to the canvas default. */}
          {!(["auto-layout", "canvas", "ellipse", "group", "image", "rectangle", "text"] as ChatShellInspectorSelection[]).includes(selection) ? <AdCanvasInspector {...schema} /> : null}
        </div>
      </aside>
    </ScenePaletteContext.Provider>
  );
}
