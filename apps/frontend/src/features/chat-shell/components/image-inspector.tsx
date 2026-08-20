"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import {
  backgroundFillCommits,
  customSizeForPreset,
  type SceneInspectorState,
} from "@/features/design-editor/adapter/scene-hydrate";
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
  const [picked, setPicked] = useState("");
  /** The swatch value this row is showing — a token name or a colour. */
  const value = picked === "" ? hydratedValue : picked;
  return {
    color: scenePaletteColor(palette, value) ?? value,
    onColorChange: (hex: string) => {
      setPicked("");
      onHex(hex);
    },
    // Absent options mean the picker is showing the DUMMY's fixture palette,
    // whose labels name no token this document has — so no token handler is
    // offered at all, and a pick from that list commits its colour instead.
    onTokenChange: paletteOptions && ((label: string) => {
      setPicked(label);
      onToken(label);
    }),
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
  const strokeRow = useAdColorRow({
    hydratedValue: state.strokeColor,
    onHex: (hex) => setValue("strokeColor", hex),
    onToken: (label) => setValue("tokenStrokeColor", label),
    paletteOptions,
  });

  return (
    <>
      <Section id="typography" label="Typography" open={state.openSections.typography} toggle={() => toggleSection("typography")}>
        <InspectorField label="Color"><ColorControl color={colorRow.color} onColorChange={colorRow.onColorChange} onTokenChange={colorRow.onTokenChange} options={paletteOptions} /></InspectorField>
        <InspectorField label="Font"><InspectorSelect label="Font family" onChange={(value) => setValue("fontFamily", value)} options={fontOptions} value={state.fontFamily} /></InspectorField>
        <div className={styles.fieldGrid}>
          {/* §2 delta (contract row 2): the size select becomes a free number. */}
          <InspectorField label="Size"><InspectorInput ariaLabel="Font size" onChange={(value) => setValue("fontSize", value)} value={state.fontSize} /></InspectorField>
          <InspectorField label="Weight"><InspectorSelect label="Font weight" onChange={(value) => setValue("fontWeight", value)} options={FONT_WEIGHT_OPTIONS} value={state.fontWeight} /></InspectorField>
        </div>
        <InspectorField label="Alignment"><TextAlignment horizontal={state.horizontalAlignment} onHorizontalChange={(value) => setValue("horizontalAlignment", value)} onVerticalChange={(value) => setValue("verticalAlignment", value)} vertical={state.verticalAlignment} /></InspectorField>
      </Section>
      <Section id="stroke" label="Stroke" open={state.openSections.stroke} toggle={() => toggleSection("stroke")}>
        <InspectorField label="Color"><ColorControl color={strokeRow.color} onColorChange={strokeRow.onColorChange} onTokenChange={strokeRow.onTokenChange} options={paletteOptions} /></InspectorField>
        <InspectorField label="Width"><InspectorInput ariaLabel="Stroke width" onChange={(value) => setValue("strokeWidth", value)} value={state.strokeWidth} /></InspectorField>
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

function AdImageInspector({
  addressing,
  hydrated,
  onSelectionChange,
  ...binding
}: AdSchemaBinding & {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
}) {
  const controller = useInspectorController(
    [],
    "image",
    hydrated ?? undefined,
    addressing,
  );
  const { setNestedValue, setValue, state, toggleSection } = controller;
  return (
    <>
      {/* §2 delta (contract row 7 / §5): the image "Link to" section is removed
          — an ad image carries no href. */}
      <Section id="fill" label="Fill" open={state.openSections.fill} toggle={() => toggleSection("fill")}>
        <InspectorField label="Image"><InspectorImageUpload onFileSelect={(file) => controller.requestAction(`replace-image:${file.name}`)} src="/icons/chat-shell/inspector/web/image-preview.png" /></InspectorField>
        <InspectorField label="Mode"><InspectorSelect label="Image fill mode" onChange={(value) => setValue("fillMode", value)} options={FILL_MODES} value={state.fillMode} /></InspectorField>
      </Section>
      <Section id="shape" label="Shape" open={state.openSections.shape} toggle={() => toggleSection("shape")}>
        <InspectorField label="Radius"><RadiusControls onChange={(corner, value) => setNestedValue("radius", corner, value)} values={state.radius} /></InspectorField>
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
  note = null,
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
  /** AD2.7: a transient informational note (the 409 quiet reload). */
  note?: string | null;
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
  const schema = { addressing, hydrated, onSelectionChange, ...layers };

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
          {selection === "image" ? <AdImageInspector {...schema} /> : null}
          {dummySelection ? <AdDummyInspector onSelectionChange={onSelectionChange} selection={selection} suppressAutoLayoutSection={suppressAutoLayoutSection} {...layers} /> : null}
          {/* `"button"` is deliberately absent from this list: with its schema
              hidden (row 7) it falls through to the canvas default. */}
          {!(["auto-layout", "canvas", "ellipse", "group", "image", "rectangle", "text"] as ChatShellInspectorSelection[]).includes(selection) ? <AdCanvasInspector {...schema} /> : null}
        </div>
      </aside>
    </ScenePaletteContext.Provider>
  );
}
