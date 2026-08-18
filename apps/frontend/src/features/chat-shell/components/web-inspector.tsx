"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { WebLayerRow } from "@/features/design-editor/adapter/layers";
import {
  themeColorForToken,
  type ThemeColorOption,
} from "@/features/design-editor/adapter/theme-options";
import type { ChatShellInspectorSelection } from "../model/chat-shell";
import { CHAT_SHELL_INSPECTOR_SELECTIONS } from "../model/chat-shell";
import {
  useInspectorController,
  useInspectorLayerTree,
  type InspectorEventAddressing,
  type InspectorPresentationState,
} from "../hooks/use-inspector-controller";
import {
  ColorControl,
  InspectorDecoratedSelect,
  InspectorField,
  InspectorHeader,
  InspectorIcon,
  InspectorImageUpload,
  InspectorInput,
  InspectorLayerRow,
  InspectorSection,
  InspectorSelect,
  InspectorTokenControl,
} from "./inspector-primitives";
import styles from "./chat-shell.module.css";

const FONT_OPTIONS = ["Inter", "Satoshi Variable", "Season Serif", "DM Mono"] as const;
// §6(5): 13 dropped from the size options; 32 maps to 3xl.
const FONT_SIZE_OPTIONS = ["12", "14", "16", "18", "20", "24", "32"] as const;
// W3.2 §2 additions: the text style select (ruling 25) and the line-spacing
// select (ruling 26) — the two founder-ordered typography additions.
const TEXT_STYLE_OPTIONS = ["Display", "H1", "H2", "H3", "H4", "Body", "Small", "Overline"] as const;
const LINE_SPACING_OPTIONS = ["none", "tight", "snug", "normal", "relaxed", "loose"] as const;
const FONT_WEIGHT_OPTIONS = ["Regular", "Medium", "Semi Bold", "Bold"] as const;
const FILL_MODE_OPTIONS = ["Fit", "Fill", "Stretch", "Tile"] as const;
const BUTTON_STYLE_OPTIONS = ["Primary", "Secondary", "Transparent", "Critical"] as const;
const ICON_OPTIONS = ["Apple"] as const;
const ICON_SIZE_OPTIONS = ["Small", "Medium", "Large"] as const;
const ICON_STROKE_OPTIONS = ["Default", "Thin", "Bold"] as const;
const INSPECTOR_TITLES: Record<ChatShellInspectorSelection, string> = {
  button: "Button",
  canvas: "Canvas",
  container: "Container",
  icon: "Icon",
  image: "Image1",
  section: "Section",
  text: "Text34",
};
const INSPECTOR_REVIEW_LABELS: Record<ChatShellInspectorSelection, string> = {
  button: "Button",
  canvas: "Canvas",
  container: "Container",
  icon: "Icon",
  image: "Image",
  section: "Section",
  text: "Text",
};
type InspectorController = ReturnType<typeof useInspectorController>;
type InspectorLayerTreeController = ReturnType<typeof useInspectorLayerTree>;

// W2.3: when the caller supplies real document layer rows, every schema's
// Layers section renders them instead of its fixture tree. The context keeps
// the seven schema views untouched except for the one fallback expression at
// each Layers site.
const DocumentLayersContext = createContext<ReactNode>(null);

function SchemaLayers({ fallback }: { fallback: ReactNode }) {
  const real = useContext(DocumentLayersContext);
  return <>{real ?? fallback}</>;
}

// W4.0: the document's real theme tokens for every ColorControl in this panel,
// carried as data (the seam rule: presentation never fetches). Undefined — the
// chats route, any mount without a document theme — leaves every picker on the
// dummy's fixture palette, unchanged. Only the text schema's Color control
// consumes it today; the other schemas' color controls join in their own W4
// tasks.
const ThemeColorsContext = createContext<readonly ThemeColorOption[] | undefined>(
  undefined,
);

function useThemeColors() {
  return useContext(ThemeColorsContext);
}

/** W2.3: the real layer tree — rows built from the document hierarchy
 * (design-editor `buildWebLayerRows`, nesting capped at depth 1 per ruling
 * 41), rendered with the dummy's own `InspectorLayerRow` primitive. Depth-0
 * rows expand/collapse locally (born expanded); clicking any row selects its
 * canvas node through the bridge. */
function DocumentLayers({
  onSelectLayer,
  rows,
}: {
  onSelectLayer?: (nodeId: string) => void;
  rows: WebLayerRow[];
}) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  return (
    <div className={styles.layerList}>
      {rows.map((row) => {
        if (row.parentId && collapsed[row.parentId]) return null;
        return (
          <InspectorLayerRow
            active={row.active}
            depth={row.depth}
            expandable={row.expandable}
            expanded={row.expandable ? !collapsed[row.nodeId] : undefined}
            icon={row.icon}
            key={row.nodeId}
            label={row.label}
            onClick={() => {
              if (row.expandable) {
                setCollapsed((current) => ({
                  ...current,
                  [row.nodeId]: !current[row.nodeId],
                }));
              }
              onSelectLayer?.(row.nodeId);
            }}
          />
        );
      })}
    </div>
  );
}

function TextAlignment({
  horizontal,
  onHorizontalChange,
  onVerticalChange,
  vertical,
  verticalHidden = false,
}: {
  horizontal: "center" | "left" | "right";
  onHorizontalChange: (value: "center" | "left" | "right") => void;
  onVerticalChange: (value: "bottom" | "middle" | "top") => void;
  vertical: "bottom" | "middle" | "top";
  /** W3.2 (ruling 8): the text schema hides vertical alignment. */
  verticalHidden?: boolean;
}) {
  const horizontalOptions = [
    ["left", "align-left"],
    ["center", "align-center"],
    ["right", "align-right"],
  ] as const;
  const verticalOptions = [
    ["top", "align-top"],
    ["middle", "align-middle"],
    ["bottom", "align-bottom"],
  ] as const;

  return (
    <div className={styles.alignmentGroups}>
      <div aria-label="Horizontal alignment" className={styles.alignmentControl} role="group">
        {horizontalOptions.map(([value, icon]) => (
          <button
            aria-label={`Align ${value}`}
            aria-pressed={horizontal === value}
            className={horizontal === value ? styles.alignmentActive : ""}
            key={value}
            onClick={() => onHorizontalChange(value)}
            type="button"
          >
            <InspectorIcon name={icon} size={12} />
          </button>
        ))}
      </div>
      {verticalHidden ? null : (
      <div
        aria-label="Vertical alignment"
        className={`${styles.alignmentControl} ${styles.verticalAlignment}`}
        role="group"
      >
        {verticalOptions.map(([value, icon]) => (
          <button
            aria-label={`Align ${value}`}
            aria-pressed={vertical === value}
            className={vertical === value ? styles.alignmentActive : ""}
            key={value}
            onClick={() => onVerticalChange(value)}
            type="button"
          >
            <InspectorIcon name={icon} size={12} />
          </button>
        ))}
      </div>
      )}
    </div>
  );
}

/** W3.2 (R3, founder-ordered delta): the four per-side boxes collapse to two
 * axis boxes (X/Y). Typed values draft locally and COMMIT on blur/Enter — the
 * dummy's own commit model — so the write path never sees per-keystroke
 * events. */
function PaddingXYControls({
  onCommit,
  values,
}: {
  onCommit: (axis: "x" | "y", value: string) => void;
  values: Record<"bottom" | "left" | "right" | "top", string>;
}) {
  const [draftX, setDraftX] = useState(values.left);
  const [draftY, setDraftY] = useState(values.top);
  const commit = (axis: "x" | "y") => {
    const draft = axis === "x" ? draftX : draftY;
    if (draft !== (axis === "x" ? values.left : values.top)) {
      onCommit(axis, draft);
    }
  };
  return (
    <div className={styles.paddingGrid}>
      <span
        className={`${styles.inspectorControl} ${styles.inspectorInputControl}`}
        onBlur={() => commit("x")}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit("x");
        }}
      >
        <span className={styles.fieldPrefix}>X</span>
        <input
          aria-label="Horizontal padding"
          onChange={(event) => setDraftX(event.target.value)}
          value={draftX}
        />
      </span>
      <span
        className={`${styles.inspectorControl} ${styles.inspectorInputControl}`}
        onBlur={() => commit("y")}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit("y");
        }}
      >
        <span className={styles.fieldPrefix}>Y</span>
        <input
          aria-label="Vertical padding"
          onChange={(event) => setDraftY(event.target.value)}
          value={draftY}
        />
      </span>
    </div>
  );
}

function PaddingControls({
  onChange,
  values,
}: {
  onChange: (side: "bottom" | "left" | "right" | "top", value: string) => void;
  values: Record<"bottom" | "left" | "right" | "top", string>;
}) {
  return (
    <div className={styles.paddingGrid}>
      <InspectorInput ariaLabel="Left padding" onChange={(value) => onChange("left", value)} prefix="L" value={values.left} />
      <InspectorInput ariaLabel="Top padding" onChange={(value) => onChange("top", value)} prefix="T" value={values.top} />
      <InspectorInput ariaLabel="Right padding" onChange={(value) => onChange("right", value)} prefix="R" value={values.right} />
      <InspectorInput ariaLabel="Bottom padding" onChange={(value) => onChange("bottom", value)} prefix="B" value={values.bottom} />
    </div>
  );
}

export function RadiusControls({
  onChange,
  values,
}: {
  onChange: (
    corner: "all" | "bottomLeft" | "bottomRight" | "topLeft" | "topRight",
    value: string,
  ) => void;
  values: Record<"all" | "bottomLeft" | "bottomRight" | "topLeft" | "topRight", string>;
}) {
  const applyAll = () => {
    (["topLeft", "topRight", "bottomLeft", "bottomRight"] as const).forEach((corner) =>
      onChange(corner, values.all),
    );
  };

  return (
    <>
      <div className={styles.radiusMainRow}>
        <InspectorInput
          ariaLabel="All corner radius"
          className={styles.radiusValue}
          leading={<InspectorIcon name="radius-all" size={16} />}
          onChange={(value) => onChange("all", value)}
          value={values.all}
        />
        <button aria-label="Apply radius to all corners" className={styles.scanButton} onClick={applyAll} type="button">
          <InspectorIcon name="radius-scan" size={12} />
        </button>
      </div>
      <div className={styles.cornerRadiusGrid}>
        {([
          ["topLeft", "radius-top-left"],
          ["topRight", "radius-top-right"],
          ["bottomLeft", "radius-bottom-left"],
          ["bottomRight", "radius-bottom-right"],
        ] as const).map(([corner, icon]) => (
          <span className={`${styles.inspectorControl} ${styles.inspectorInputControl} ${styles.cornerRadiusField}`} key={corner}>
            <InspectorIcon name={icon} size={16} />
            <input
              aria-label={`${corner} radius`}
              onChange={(event) => onChange(corner, event.target.value)}
              value={values[corner]}
            />
          </span>
        ))}
      </div>
    </>
  );
}

function TextLayers({
  onSelectionChange,
  tree,
}: {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  tree: InspectorLayerTreeController;
}) {
  return (
    <div className={styles.layerList}>
      <InspectorLayerRow
        active={tree.activeLayer === "div1"}
        expanded={tree.expandedLayers.div1}
        expandable
        icon="div"
        label="Div1"
        onClick={() => { tree.selectLayer("div1"); tree.toggleLayer("div1"); }}
      />
      {tree.expandedLayers.div1 ? (
        <InspectorLayerRow
          active={tree.activeLayer === "text"}
          depth={1}
          icon="type"
          label="Text"
          onClick={() => { tree.selectLayer("text"); onSelectionChange("text"); }}
          trailing
        />
      ) : null}
      <InspectorLayerRow
        active={tree.activeLayer === "div2"}
        expanded={tree.expandedLayers.div2}
        expandable
        icon="div"
        label="Div2"
        onClick={() => { tree.selectLayer("div2"); tree.toggleLayer("div2"); }}
      />
      {tree.expandedLayers.div2 ? (
        <>
          <InspectorLayerRow active={tree.activeLayer === "rectangle"} depth={1} icon="rectangle" label="Rectangle" onClick={() => tree.selectLayer("rectangle")} />
          <InspectorLayerRow active={tree.activeLayer === "ellipse"} depth={1} icon="ellipse" label="Ellipse" onClick={() => tree.selectLayer("ellipse")} />
        </>
      ) : null}
    </div>
  );
}

function ImageLayers({
  onSelectionChange,
  tree,
}: {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  tree: InspectorLayerTreeController;
}) {
  return (
    <div className={styles.layerList}>
      <InspectorLayerRow expanded={tree.expandedLayers.div1} expandable icon="div" label="Div1" onClick={() => tree.toggleLayer("div1")} />
      {tree.expandedLayers.div1 ? (
        <>
          <InspectorLayerRow active={tree.activeLayer === "text"} depth={1} icon="type" label="Text" onClick={() => { tree.selectLayer("text"); onSelectionChange("text"); }} />
          <InspectorLayerRow active={tree.activeLayer === "image"} depth={1} icon="image" label="Image" onClick={() => { tree.selectLayer("image"); onSelectionChange("image"); }} trailing />
        </>
      ) : null}
      <InspectorLayerRow expanded={tree.expandedLayers.div2} expandable icon="div" label="Div2" onClick={() => tree.toggleLayer("div2")} />
      {tree.expandedLayers.div2 ? <InspectorLayerRow depth={1} icon="rectangle" label="Rectangle" /> : null}
    </div>
  );
}

function ButtonLayers({
  onSelectionChange,
  tree,
}: {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  tree: InspectorLayerTreeController;
}) {
  return (
    <div className={styles.layerList}>
      <InspectorLayerRow expanded={tree.expandedLayers.div1} expandable icon="div" label="Div1" onClick={() => tree.toggleLayer("div1")} />
      {tree.expandedLayers.div1 ? (
        <InspectorLayerRow
          active={tree.activeLayer === "button"}
          depth={1}
          icon="rectangle"
          label="Button"
          onClick={() => { tree.selectLayer("button"); onSelectionChange("button"); }}
          trailing
        />
      ) : null}
      <InspectorLayerRow expanded={tree.expandedLayers.div2} expandable icon="div" label="Div2" onClick={() => tree.toggleLayer("div2")} />
      {tree.expandedLayers.div2 ? (
        <>
          <InspectorLayerRow depth={1} icon="rectangle" label="Rectangle" onClick={() => tree.selectLayer("rectangle")} />
          <InspectorLayerRow depth={1} icon="ellipse" label="Ellipse" onClick={() => tree.selectLayer("ellipse")} />
        </>
      ) : null}
    </div>
  );
}

function StructuralLayers({
  onSelectionChange,
  selection,
  tree,
}: {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  selection: Extract<ChatShellInspectorSelection, "container" | "icon" | "section">;
  tree: InspectorLayerTreeController;
}) {
  const icon = selection === "icon" ? "apple" : "div";
  const label = selection[0].toUpperCase() + selection.slice(1);
  return (
    <div className={styles.layerList}>
      <InspectorLayerRow expanded={tree.expandedLayers.div1} expandable icon="div" label="Div1" onClick={() => tree.toggleLayer("div1")} />
      {tree.expandedLayers.div1 ? (
        <InspectorLayerRow
          active={tree.activeLayer === selection}
          depth={1}
          icon={icon}
          label={label}
          onClick={() => { tree.selectLayer(selection); onSelectionChange(selection); }}
          trailing
        />
      ) : null}
      <InspectorLayerRow expanded={tree.expandedLayers.div2} expandable icon="div" label="Div2" onClick={() => tree.toggleLayer("div2")} />
      {tree.expandedLayers.div2 ? <InspectorLayerRow depth={1} icon="rectangle" label="Rectangle" onClick={() => tree.selectLayer("rectangle")} /> : null}
    </div>
  );
}

function CanvasLayers({
  onSelectionChange,
  tree,
}: {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  tree: InspectorLayerTreeController;
}) {
  return (
    <div className={styles.layerList}>
      <InspectorLayerRow active={tree.activeLayer === "text-1"} icon="type" label="Text" onClick={() => { tree.selectLayer("text-1"); onSelectionChange("text"); }} />
      <InspectorLayerRow active={tree.activeLayer === "canvas-text"} icon="type" label="Text" onClick={() => { tree.selectLayer("canvas-text"); onSelectionChange("text"); }} trailing />
      <InspectorLayerRow expanded={tree.expandedLayers.group} expandable icon="div" label="Group" onClick={() => tree.toggleLayer("group")} />
      {tree.expandedLayers.group ? (
        <>
          <InspectorLayerRow depth={1} icon="type" label="Text" />
          <InspectorLayerRow depth={1} icon="rectangle" label="Rectangle" />
        </>
      ) : null}
    </div>
  );
}

function Section({
  children,
  id,
  label,
  state,
  toggle,
}: {
  children?: ReactNode;
  id: Parameters<ReturnType<typeof useInspectorController>["toggleSection"]>[0];
  label: string;
  state: ReturnType<typeof useInspectorController>["state"];
  toggle: ReturnType<typeof useInspectorController>["toggleSection"];
}) {
  return <InspectorSection compact={id === "link"} label={label} onOpenChange={() => toggle(id)} open={state.openSections[id]}>{children}</InspectorSection>;
}

function SegmentedControl<Value extends string>({
  ariaLabel,
  onChange,
  options,
  value,
}: {
  ariaLabel: string;
  onChange: (value: Value) => void;
  options: readonly { label: ReactNode; value: Value }[];
  value: Value;
}) {
  return (
    <div aria-label={ariaLabel} className={styles.inspectorSegmentedControl} role="group">
      {options.map((option) => (
        <button
          aria-pressed={option.value === value}
          className={option.value === value ? styles.inspectorSegmentActive : ""}
          key={option.value}
          onClick={() => onChange(option.value)}
          type="button"
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function LinkSection({
  ariaLabel,
  controller,
}: {
  ariaLabel: string;
  controller: InspectorController;
}) {
  const { setValue, state, toggleSection } = controller;
  return (
    <Section id="link" label="Link to" state={state} toggle={toggleSection}>
      <InspectorField label="URL">
        <InspectorInput ariaLabel={ariaLabel} onChange={(value) => setValue("url", value)} value={state.url} />
      </InspectorField>
      <label className={styles.checkboxRow}>
        <input checked={state.openInNewTab} onChange={(event) => setValue("openInNewTab", event.target.checked)} type="checkbox" />
        <span>Open in a new tab</span>
      </label>
    </Section>
  );
}

function TokenField({
  controller,
  label,
  options,
  property,
  swatch,
  tokenProperty,
  value,
}: {
  controller: InspectorController;
  label: string;
  /** W4.4: the document's real theme tokens; with `tokenProperty` they make
   * this button a live token picker (rows 19/17). Absent → the dummy button. */
  options?: readonly ThemeColorOption[];
  property: string;
  swatch: string;
  /** W4.4: which inspector token field a pick writes
   * (`tokenTextColor`/`tokenBackgroundColor`) — the W3.1-addressed event seam,
   * so `adapter/apply.ts` turns the label into the facet write. */
  tokenProperty?: "tokenBackgroundColor" | "tokenTextColor";
  value: string;
}) {
  return (
    <InspectorField label={label}>
      <InspectorTokenControl
        label={value}
        onClick={() => controller.requestAction(`token-picker:${property}`)}
        onTokenSelect={
          tokenProperty
            ? (token) => controller.setValue(tokenProperty, token)
            : undefined
        }
        options={options}
        swatch={swatch}
      />
    </InspectorField>
  );
}

/** W4.4: the Style section shared by the container and section schemas — the
 * dummy's two token buttons, now showing the node's hydrated tokens (with the
 * theme's real swatch when the document defines it) and writing through the
 * theme-token popover (rows 19; the popover is row 17's pattern). Both schemas
 * render exactly the two fields the dummy ships. */
function StyleTokenFields({ controller }: { controller: InspectorController }) {
  const { state } = controller;
  const themeColors = useThemeColors();
  return (
    <>
      <TokenField
        controller={controller}
        label="Text color"
        options={themeColors}
        property="textColor"
        swatch={themeColorForToken(themeColors, state.tokenTextColor) ?? "#1C2028"}
        tokenProperty="tokenTextColor"
        value={state.tokenTextColor}
      />
      <TokenField
        controller={controller}
        label="Background color"
        options={themeColors}
        property="backgroundColor"
        swatch={
          themeColorForToken(themeColors, state.tokenBackgroundColor) ?? "#FFFFFF"
        }
        tokenProperty="tokenBackgroundColor"
        value={state.tokenBackgroundColor}
      />
    </>
  );
}

function LayoutSection({
  controller,
  paddingAxes = "four",
}: {
  controller: InspectorController;
  /** W3.2 (R3): "two" collapses the padding boxes to X/Y with blur/Enter
   * commit; "four" keeps the dummy's per-side boxes (until each schema's W4
   * task applies its own delta). */
  paddingAxes?: "four" | "two";
}) {
  const { setNestedValue, setPaddingAxis, state, toggleSection } = controller;
  return (
    <Section id="layout" label="Layout" state={state} toggle={toggleSection}>
      <InspectorField label="Padding">
        {paddingAxes === "two" ? (
          <PaddingXYControls
            onCommit={(axis, value) => setPaddingAxis(axis, value)}
            values={state.padding}
          />
        ) : (
          <PaddingControls onChange={(side, value) => setNestedValue("padding", side, value)} values={state.padding} />
        )}
      </InspectorField>
    </Section>
  );
}

function TextControls({
  controller,
  layerTree,
  onSelectionChange,
  showLayers,
}: {
  controller: InspectorController;
  layerTree: InspectorLayerTreeController;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  showLayers: boolean;
}) {
  const { setValue, state, toggleSection } = controller;
  const themeColors = useThemeColors();
  return (
    <>
      <LinkSection ariaLabel="Link URL" controller={controller} />
      <Section id="typography" label="Typography" state={state} toggle={toggleSection}>
        {/* R2: the theme tab's token pick is the live write path
            (tokenTextColor); the hex path stays visual-only (§3 inert).
            W4.0: the tab lists the document's real tokens, and the closed
            trigger shows the hydrated token's actual color when the theme
            has it (otherwise the dummy default stands). */}
        <InspectorField label="Color"><ColorControl color={themeColorForToken(themeColors, state.tokenTextColor) ?? state.textColor} onColorChange={(value) => setValue("textColor", value)} onTokenChange={(label) => setValue("tokenTextColor", label)} options={themeColors} /></InspectorField>
        <InspectorField label="Font"><InspectorSelect label="Font" onChange={(value) => setValue("fontFamily", value)} options={FONT_OPTIONS} value={state.fontFamily} /></InspectorField>
        {/* W3.2 §2 addition (ruling 25): the text style/variant select. */}
        <InspectorField label="Style"><InspectorSelect label="Text style" onChange={(value) => setValue("textStyle", value)} options={TEXT_STYLE_OPTIONS} value={state.textStyle} /></InspectorField>
        <div className={styles.fieldGrid}>
          <InspectorField label="Size"><InspectorSelect label="Font size" onChange={(value) => setValue("fontSize", value)} options={FONT_SIZE_OPTIONS} value={state.fontSize} /></InspectorField>
          <InspectorField label="Weight"><InspectorSelect label="Font weight" onChange={(value) => setValue("fontWeight", value)} options={FONT_WEIGHT_OPTIONS} value={state.fontWeight} /></InspectorField>
        </div>
        {/* W3.2 §2 addition (ruling 26): the line-spacing select. */}
        <InspectorField label="Line spacing"><InspectorSelect label="Line spacing" onChange={(value) => setValue("lineSpacing", value)} options={LINE_SPACING_OPTIONS} value={state.lineSpacing} /></InspectorField>
        {/* Ruling 8: vertical alignment hidden on the text schema. */}
        <InspectorField label="Alignment"><TextAlignment horizontal={state.horizontalAlignment} onHorizontalChange={(value) => setValue("horizontalAlignment", value)} onVerticalChange={(value) => setValue("verticalAlignment", value)} vertical={state.verticalAlignment} verticalHidden /></InspectorField>
      </Section>
      {/* R3: text's padding boxes collapse to the two-axis form. */}
      <LayoutSection controller={controller} paddingAxes="two" />
      <Section id="stroke" label="Stroke" state={state} toggle={toggleSection}>
        <InspectorField label="Color"><ColorControl none={state.strokeColor === "none"} /></InspectorField>
        <InspectorField label="Width"><InspectorInput ariaLabel="Stroke width" onChange={(value) => setValue("strokeWidth", value)} value={state.strokeWidth} /></InspectorField>
      </Section>
      {showLayers ? <Section id="layers" label="Layers" state={state} toggle={toggleSection}><SchemaLayers fallback={<TextLayers onSelectionChange={onSelectionChange} tree={layerTree} />} /></Section> : null}
    </>
  );
}

function CanvasControls({
  controller,
  layerTree,
  onSelectionChange,
  showLayers,
}: {
  controller: InspectorController;
  layerTree: InspectorLayerTreeController;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  showLayers: boolean;
}) {
  const { setValue, state, toggleSection } = controller;
  return (
    <>
      <Section id="background" label="Background" state={state} toggle={toggleSection}><InspectorField label="Color"><ColorControl color={state.backgroundColor} onColorChange={(value) => setValue("backgroundColor", value)} /></InspectorField></Section>
      {showLayers ? <Section id="layers" label="Layers" state={state} toggle={toggleSection}><SchemaLayers fallback={<CanvasLayers onSelectionChange={onSelectionChange} tree={layerTree} />} /></Section> : null}
    </>
  );
}

function ImageControls({
  controller,
  layerTree,
  onSelectionChange,
  showLayers,
}: {
  controller: InspectorController;
  layerTree: InspectorLayerTreeController;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  showLayers: boolean;
}) {
  const { setNestedValue, setValue, state, toggleSection } = controller;
  return (
    <>
      <LinkSection ariaLabel="Image link URL" controller={controller} />
      <Section id="fill" label="Fill" state={state} toggle={toggleSection}>
        <InspectorField label="Image">
          <InspectorImageUpload
            onFileSelect={(file) => controller.requestAction(`replace-image:${file.name}`)}
            src="/icons/chat-shell/inspector/web/image-preview.png"
          />
        </InspectorField>
        <InspectorField label="Mode"><InspectorSelect label="Image fill mode" onChange={(value) => setValue("fillMode", value)} options={FILL_MODE_OPTIONS} value={state.fillMode} /></InspectorField>
      </Section>
      <Section id="shape" label="Shape" state={state} toggle={toggleSection}><InspectorField label="Radius"><RadiusControls onChange={(corner, value) => setNestedValue("radius", corner, value)} values={state.radius} /></InspectorField></Section>
      {showLayers ? <Section id="layers" label="Layers" state={state} toggle={toggleSection}><SchemaLayers fallback={<ImageLayers onSelectionChange={onSelectionChange} tree={layerTree} />} /></Section> : null}
    </>
  );
}

function ButtonControls({
  controller,
  layerTree,
  onSelectionChange,
  showLayers,
}: {
  controller: InspectorController;
  layerTree: InspectorLayerTreeController;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  showLayers: boolean;
}) {
  const { setValue, state, toggleSection } = controller;
  return (
    <>
      <LinkSection ariaLabel="Button link URL" controller={controller} />
      <Section id="style" label="Style" state={state} toggle={toggleSection}>
        <InspectorField label="Label">
          <InspectorSelect label="Button style" onChange={(value) => setValue("buttonLabel", value)} options={BUTTON_STYLE_OPTIONS} value={state.buttonLabel} />
        </InspectorField>
        <TokenField controller={controller} label="Background color" property="backgroundColor" swatch="#00F59B" value="Primary" />
        <TokenField controller={controller} label="Text color" property="textColor" swatch="#FFFFFF" value="White" />
      </Section>
      <LayoutSection controller={controller} />
      {showLayers ? <Section id="layers" label="Layers" state={state} toggle={toggleSection}>
        <SchemaLayers fallback={<ButtonLayers onSelectionChange={onSelectionChange} tree={layerTree} />} />
      </Section> : null}
    </>
  );
}

function IconControls({
  controller,
  layerTree,
  onSelectionChange,
  showLayers,
}: {
  controller: InspectorController;
  layerTree: InspectorLayerTreeController;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  showLayers: boolean;
}) {
  const { setValue, state, toggleSection } = controller;
  return (
    <>
      <LinkSection ariaLabel="Icon link URL" controller={controller} />
      <Section id="icon" label="Icon" state={state} toggle={toggleSection}>
        <InspectorField label="Icon">
          <InspectorDecoratedSelect icon="apple" label="Icon" onChange={(value) => setValue("iconName", value)} options={ICON_OPTIONS} value={state.iconName} />
        </InspectorField>
        <TokenField controller={controller} label="Icon color" property="iconColor" swatch="#1C2028" value="Content" />
        <TokenField controller={controller} label="Background color" property="backgroundColor" swatch="#FFFFFF" value="White" />
        <div className={styles.fieldGrid}>
          <InspectorField label="Size"><InspectorSelect label="Icon size" onChange={(value) => setValue("iconSize", value)} options={ICON_SIZE_OPTIONS} value={state.iconSize} /></InspectorField>
          <InspectorField label="Stroke"><InspectorSelect label="Icon stroke" onChange={(value) => setValue("iconStroke", value)} options={ICON_STROKE_OPTIONS} value={state.iconStroke} /></InspectorField>
        </div>
      </Section>
      <LayoutSection controller={controller} />
      {showLayers ? <Section id="layers" label="Layers" state={state} toggle={toggleSection}>
        <SchemaLayers fallback={<StructuralLayers onSelectionChange={onSelectionChange} selection="icon" tree={layerTree} />} />
      </Section> : null}
    </>
  );
}

function ContainerControls({
  controller,
  layerTree,
  onSelectionChange,
  showLayers,
}: {
  controller: InspectorController;
  layerTree: InspectorLayerTreeController;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  showLayers: boolean;
}) {
  const { setValue, state, toggleSection } = controller;
  return (
    <>
      <LinkSection ariaLabel="Container link URL" controller={controller} />
      <Section id="style" label="Style" state={state} toggle={toggleSection}>
        {/* W4.4 (row 19): the two token buttons, hydrated + live. */}
        <StyleTokenFields controller={controller} />
      </Section>
      <Section id="alignment" label="Alignment" state={state} toggle={toggleSection}>
        <SegmentedControl
          ariaLabel="Container layout mode"
          onChange={(value) => setValue("layoutMode", value)}
          options={([
            { label: "Flex", value: "Flex" },
            { label: "Grid", value: "Grid" },
            { label: "Hide", value: "Hide" },
          ] as const)}
          value={state.layoutMode}
        />
      </Section>
      <LayoutSection controller={controller} />
      {showLayers ? <Section id="layers" label="Layers" state={state} toggle={toggleSection}>
        <SchemaLayers fallback={<StructuralLayers onSelectionChange={onSelectionChange} selection="container" tree={layerTree} />} />
      </Section> : null}
    </>
  );
}

function SectionControls({
  controller,
  layerTree,
  onSelectionChange,
  showLayers,
}: {
  controller: InspectorController;
  layerTree: InspectorLayerTreeController;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  showLayers: boolean;
}) {
  const { setValue, state, toggleSection } = controller;
  return (
    <>
      <LinkSection ariaLabel="Section link URL" controller={controller} />
      <Section id="style" label="Style" state={state} toggle={toggleSection}>
        {/* W4.4 (row 19): the two token buttons, hydrated + live. */}
        <StyleTokenFields controller={controller} />
      </Section>
      <Section id="alignment" label="Alignment" state={state} toggle={toggleSection}>
        <InspectorField label="Direction">
          <SegmentedControl
            ariaLabel="Section direction"
            onChange={(value) => setValue("direction", value)}
            options={([
              { label: <InspectorIcon name="move-horizontal" size={12} />, value: "horizontal" },
              { label: <InspectorIcon name="move-vertical" size={12} />, value: "vertical" },
            ] as const)}
            value={state.direction}
          />
        </InspectorField>
        <InspectorField label="Gap">
          <InspectorInput ariaLabel="Section gap" leading={<InspectorIcon name="gap" size={16} />} onChange={(value) => setValue("gap", value)} value={state.gap} />
        </InspectorField>
        <InspectorField label="Wrap">
          <SegmentedControl
            ariaLabel="Section wrapping"
            onChange={(value) => setValue("wrap", value === "yes")}
            options={([
              { label: "Yes", value: "yes" },
              { label: "No", value: "no" },
            ] as const)}
            value={state.wrap ? "yes" : "no"}
          />
        </InspectorField>
      </Section>
      <LayoutSection controller={controller} />
      {showLayers ? <Section id="layers" label="Layers" state={state} toggle={toggleSection}>
        <SchemaLayers fallback={<StructuralLayers onSelectionChange={onSelectionChange} selection="section" tree={layerTree} />} />
      </Section> : null}
    </>
  );
}

export function WebInspector({
  addressing,
  error = null,
  hydrated,
  layers,
  note = null,
  onSelectionChange,
  onSelectLayer,
  reviewMenuEnabled = false,
  selection,
  showLayers = true,
  themeColors,
}: {
  /** W3.2: an inline write error (422 first diagnostic / transport). The
   * minimal pre-W3.3 floor — the save-failure surface is the W3.3 founder
   * gate; do not grow this beyond one line without that ruling. */
  error?: string | null;
  /** W3.2: a transient informational note (409 quiet reload). Same W3.3
   * floor as `error`. */
  note?: string | null;
  /** W3.1: write addressing stamped onto every inspector event this panel
   * dispatches — passed through to the controllers verbatim. */
  addressing?: InspectorEventAddressing;
  /** W2.2: real values for the selected node (design-editor hydrate adapter),
   * merged over the dummy defaults at mount. Callers remount per selection. */
  hydrated?: Partial<InspectorPresentationState>;
  /** W2.3: real document layer rows (design-editor `buildWebLayerRows`).
   * When present, every schema's Layers section renders them instead of its
   * fixture tree; absent keeps the dummy fixtures untouched. */
  layers?: WebLayerRow[];
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  /** W2.3: a layer-row click — callers send bridge `selectNode`. */
  onSelectLayer?: (nodeId: string) => void;
  reviewMenuEnabled?: boolean;
  selection: ChatShellInspectorSelection;
  showLayers?: boolean;
  /** W4.0: the document's real theme tokens (design-editor
   * `buildThemeColorOptions`) for the color pickers' Theme tab; absent keeps
   * the dummy's fixture palette. */
  themeColors?: readonly ThemeColorOption[];
}) {
  const inspectorRef = useRef<HTMLElement>(null);
  const [reviewMenuOpen, setReviewMenuOpen] = useState(false);
  const canvasController = useInspectorController([], "canvas", hydrated, addressing);
  const textController = useInspectorController(["link"], "text", hydrated, addressing);
  const imageController = useInspectorController(["link"], "image", hydrated, addressing);
  const buttonController = useInspectorController(["link"], "button", hydrated, addressing);
  const iconController = useInspectorController(["link"], "icon", hydrated, addressing);
  const containerController = useInspectorController(["link"], "container", hydrated, addressing);
  const sectionController = useInspectorController(["link"], "section", hydrated, addressing);
  const documentLayers = layers ? (
    <DocumentLayers onSelectLayer={onSelectLayer} rows={layers} />
  ) : null;
  const canvasLayerTree = useInspectorLayerTree("canvas-text", ["group"], "canvas");
  const textLayerTree = useInspectorLayerTree("text", ["div1", "div2"], "text");
  const imageLayerTree = useInspectorLayerTree("image", ["div1", "div2"], "image");
  const buttonLayerTree = useInspectorLayerTree("button", ["div1", "div2"], "button");
  const iconLayerTree = useInspectorLayerTree("icon", ["div1", "div2"], "icon");
  const containerLayerTree = useInspectorLayerTree("container", ["div1", "div2"], "container");
  const sectionLayerTree = useInspectorLayerTree("section", ["div1", "div2"], "section");
  const controllers: Record<ChatShellInspectorSelection, InspectorController> = {
    button: buttonController,
    canvas: canvasController,
    container: containerController,
    icon: iconController,
    image: imageController,
    section: sectionController,
    text: textController,
  };
  const activeController = controllers[selection];

  useEffect(() => {
    if (!reviewMenuOpen) return;

    const dismiss = (event: PointerEvent) => {
      if (!inspectorRef.current?.contains(event.target as Node)) {
        setReviewMenuOpen(false);
      }
    };
    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setReviewMenuOpen(false);
    };

    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", dismissOnEscape);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", dismissOnEscape);
    };
  }, [reviewMenuOpen]);

  const reviewMenu = reviewMenuEnabled && reviewMenuOpen ? (
    <div aria-label="Preview inspector element types" className={styles.inspectorVariantMenu} role="menu">
      <span className={styles.inspectorVariantMenuLabel}>Element controls</span>
      {CHAT_SHELL_INSPECTOR_SELECTIONS.map((variant) => (
        <button
          aria-checked={selection === variant}
          className={selection === variant ? styles.inspectorVariantMenuItemActive : ""}
          key={variant}
          onClick={() => {
            onSelectionChange(variant);
            setReviewMenuOpen(false);
          }}
          role="menuitemradio"
          type="button"
        >
          <span>{INSPECTOR_REVIEW_LABELS[variant]}</span>
          <span aria-hidden="true">{selection === variant ? "✓" : ""}</span>
        </button>
      ))}
    </div>
  ) : null;

  return (
    <aside aria-label="Web inspector" className={styles.inspector} ref={inspectorRef}>
      <div className={styles.inspectorRail}>
        <InspectorHeader
          actionMenu={reviewMenu}
          elementActions={selection !== "canvas"}
          locked={activeController.state.locked}
          moreActionsExpanded={reviewMenuEnabled ? reviewMenuOpen : undefined}
          moreActionsHasPopup={reviewMenuEnabled}
          onLockToggle={() => activeController.setValue("locked", !activeController.state.locked)}
          onMoreActions={() => {
            activeController.requestAction("more-actions");
            if (reviewMenuEnabled) setReviewMenuOpen((open) => !open);
          }}
          onVisibilityToggle={() => activeController.setValue("visible", !activeController.state.visible)}
          title={INSPECTOR_TITLES[selection]}
          visible={activeController.state.visible}
        />
        {/* W3.2 floor pending the W3.3 founder gate: one inline line for the
            write path's note (409 quiet reload) / error (422 diagnostic). */}
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
        <ThemeColorsContext.Provider value={themeColors}>
          <DocumentLayersContext.Provider value={documentLayers}>
            {selection === "canvas" ? <CanvasControls controller={canvasController} layerTree={canvasLayerTree} onSelectionChange={onSelectionChange} showLayers={showLayers} /> : null}
            {selection === "text" ? <TextControls controller={textController} layerTree={textLayerTree} onSelectionChange={onSelectionChange} showLayers={showLayers} /> : null}
            {selection === "image" ? <ImageControls controller={imageController} layerTree={imageLayerTree} onSelectionChange={onSelectionChange} showLayers={showLayers} /> : null}
            {selection === "button" ? <ButtonControls controller={buttonController} layerTree={buttonLayerTree} onSelectionChange={onSelectionChange} showLayers={showLayers} /> : null}
            {selection === "icon" ? <IconControls controller={iconController} layerTree={iconLayerTree} onSelectionChange={onSelectionChange} showLayers={showLayers} /> : null}
            {selection === "container" ? <ContainerControls controller={containerController} layerTree={containerLayerTree} onSelectionChange={onSelectionChange} showLayers={showLayers} /> : null}
            {selection === "section" ? <SectionControls controller={sectionController} layerTree={sectionLayerTree} onSelectionChange={onSelectionChange} showLayers={showLayers} /> : null}
          </DocumentLayersContext.Provider>
        </ThemeColorsContext.Provider>
      </div>
    </aside>
  );
}
