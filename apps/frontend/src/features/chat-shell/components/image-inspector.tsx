"use client";

import type { ReactNode } from "react";
import type { ChatShellInspectorSelection } from "../model/chat-shell";
import {
  useInspectorController,
  useInspectorLayerTree,
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
  InspectorTokenControl,
} from "./inspector-primitives";
import styles from "./chat-shell.module.css";
import { RadiusControls } from "./web-inspector";

const FONT_OPTIONS = ["Inter", "Satoshi Variable", "Season Serif", "DM Mono"] as const;
const FONT_SIZE_OPTIONS = ["12", "13", "14", "16", "18", "20", "24", "32"] as const;
const FONT_WEIGHT_OPTIONS = ["Regular", "Medium", "Semi Bold", "Bold"] as const;
const FILL_MODES = ["Fit", "Fill", "Stretch", "Tile"] as const;
const BUTTON_STYLE_OPTIONS = ["Primary", "Secondary", "Transparent", "Critical"] as const;
const SIZE_PRESETS = [
  "Linkedin square (1:1) - 1024x1024",
  "Instagram portrait (4:5) - 1080x1350",
  "Story (9:16) - 1080x1920",
] as const;

type AdSelectableLayer = "button" | "image" | "text";

function AdLayers({
  onSelectionChange,
  selected,
}: {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  selected: ChatShellInspectorSelection;
}) {
  const tree = useInspectorLayerTree(selected, ["group"], selected);

  const select = (layer: string, selection?: AdSelectableLayer) => {
    tree.selectLayer(layer);
    if (selection) onSelectionChange(selection);
  };

  return (
    <div className={styles.layerList}>
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
        icon="div"
        label="Group"
        onClick={() => tree.toggleLayer("group")}
      />
      {tree.expandedLayers.group ? (
        <>
          <InspectorLayerRow depth={1} icon="type" label="Text" onClick={() => select("group-text", "text")} />
          <InspectorLayerRow depth={1} icon="rectangle" label="Rectangle" onClick={() => select("group-rectangle")} />
        </>
      ) : null}
      <InspectorLayerRow active={tree.activeLayer === "rectangle"} icon="rectangle" label="Rectangle" onClick={() => select("rectangle")} />
      <InspectorLayerRow active={tree.activeLayer === "ellipse"} icon="ellipse" label="Ellipse" onClick={() => select("ellipse")} />
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
  horizontal: "center" | "left" | "right";
  onHorizontalChange: (value: "center" | "left" | "right") => void;
  onVerticalChange: (value: "bottom" | "middle" | "top") => void;
  vertical: "bottom" | "middle" | "top";
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

function Section({
  children,
  compact = false,
  id,
  label,
  open,
  toggle,
}: {
  children?: ReactNode;
  compact?: boolean;
  id: Parameters<ReturnType<typeof useInspectorController>["toggleSection"]>[0];
  label: string;
  open: boolean;
  toggle: () => void;
}) {
  return <InspectorSection compact={compact} key={id} label={label} onOpenChange={toggle} open={open}>{children}</InspectorSection>;
}

function AdTextInspector({
  onSelectionChange,
}: {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
}) {
  const controller = useInspectorController([], "text");
  const { requestAction, setNestedValue, setValue, state, toggleSection } = controller;

  return (
    <>
      <Section id="typography" label="Typography" open={state.openSections.typography} toggle={() => toggleSection("typography")}>
        <InspectorField label="Color"><ColorControl color={state.textColor} onColorChange={(value) => setValue("textColor", value)} /></InspectorField>
        <InspectorField label="Font"><InspectorSelect label="Font family" onChange={(value) => setValue("fontFamily", value)} options={FONT_OPTIONS} value={state.fontFamily} /></InspectorField>
        <div className={styles.fieldGrid}>
          <InspectorField label="Size"><InspectorSelect label="Font size" onChange={(value) => setValue("fontSize", value)} options={FONT_SIZE_OPTIONS} value={state.fontSize} /></InspectorField>
          <InspectorField label="Weight"><InspectorSelect label="Font weight" onChange={(value) => setValue("fontWeight", value)} options={FONT_WEIGHT_OPTIONS} value={state.fontWeight} /></InspectorField>
        </div>
        <InspectorField label="Alignment"><TextAlignment horizontal={state.horizontalAlignment} onHorizontalChange={(value) => setValue("horizontalAlignment", value)} onVerticalChange={(value) => setValue("verticalAlignment", value)} vertical={state.verticalAlignment} /></InspectorField>
      </Section>
      <Section id="stroke" label="Stroke" open={state.openSections.stroke} toggle={() => toggleSection("stroke")}>
        <InspectorField label="Color"><ColorControl color={state.strokeColor} onColorChange={(value) => setValue("strokeColor", value)} /></InspectorField>
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
        <AdLayers onSelectionChange={onSelectionChange} selected="text" />
      </Section>
    </>
  );
}

function AdCanvasInspector({
  onSelectionChange,
}: {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
}) {
  const controller = useInspectorController([], "canvas");
  const { setValue, state, toggleSection } = controller;
  return (
    <>
      <Section id="dimensions" label="Dimensions" open={state.openSections.dimensions} toggle={() => toggleSection("dimensions")}>
        <InspectorField label="Size"><InspectorSelect label="Canvas dimensions" onChange={(value) => setValue("sizePreset", value)} options={SIZE_PRESETS} value={state.sizePreset} /></InspectorField>
      </Section>
      <Section id="background" label="Background" open={state.openSections.background} toggle={() => toggleSection("background")}>
        <InspectorField label="Fill">
          <BackgroundFillControl
            fill={state.backgroundFill}
            onFillChange={(value) => setValue("backgroundFill", value)}
            onSolidColorChange={(value) => setValue("backgroundColor", value)}
            solidColor={state.backgroundColor}
          />
        </InspectorField>
      </Section>
      <Section id="layers" label="Layers" open={state.openSections.layers} toggle={() => toggleSection("layers")}>
        <AdLayers onSelectionChange={onSelectionChange} selected="canvas" />
      </Section>
    </>
  );
}

function AdImageInspector({
  onSelectionChange,
}: {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
}) {
  const controller = useInspectorController([], "image");
  const { setNestedValue, setValue, state, toggleSection } = controller;
  return (
    <>
      <Section compact id="link" label="Link to" open={state.openSections.link} toggle={() => toggleSection("link")}>
        <InspectorField label="URL"><InspectorInput ariaLabel="Image link URL" onChange={(value) => setValue("url", value)} value={state.url} /></InspectorField>
        <label className={styles.checkboxRow}><input checked={state.openInNewTab} onChange={(event) => setValue("openInNewTab", event.target.checked)} type="checkbox" /><span>Open in a new tab</span></label>
      </Section>
      <Section id="fill" label="Fill" open={state.openSections.fill} toggle={() => toggleSection("fill")}>
        <InspectorField label="Image"><InspectorImageUpload onFileSelect={(file) => controller.requestAction(`replace-image:${file.name}`)} src="/icons/chat-shell/inspector/web/image-preview.png" /></InspectorField>
        <InspectorField label="Mode"><InspectorSelect label="Image fill mode" onChange={(value) => setValue("fillMode", value)} options={FILL_MODES} value={state.fillMode} /></InspectorField>
      </Section>
      <Section id="shape" label="Shape" open={state.openSections.shape} toggle={() => toggleSection("shape")}>
        <InspectorField label="Radius"><RadiusControls onChange={(corner, value) => setNestedValue("radius", corner, value)} values={state.radius} /></InspectorField>
      </Section>
      <Section id="layers" label="Layers" open={state.openSections.layers} toggle={() => toggleSection("layers")}>
        <AdLayers onSelectionChange={onSelectionChange} selected="image" />
      </Section>
    </>
  );
}

function AdButtonInspector({
  onSelectionChange,
}: {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
}) {
  const controller = useInspectorController([], "button");
  const { setNestedValue, setValue, state, toggleSection } = controller;
  return (
    <>
      <Section compact id="link" label="Link to" open={state.openSections.link} toggle={() => toggleSection("link")}>
        <InspectorField label="URL"><InspectorInput ariaLabel="Button link URL" onChange={(value) => setValue("url", value)} value={state.url} /></InspectorField>
        <label className={styles.checkboxRow}><input checked={state.openInNewTab} onChange={(event) => setValue("openInNewTab", event.target.checked)} type="checkbox" /><span>Open in a new tab</span></label>
      </Section>
      <Section id="style" label="Style" open={state.openSections.style} toggle={() => toggleSection("style")}>
        <InspectorField label="Button type"><InspectorSelect label="Button type" onChange={(value) => setValue("buttonLabel", value)} options={BUTTON_STYLE_OPTIONS} value={state.buttonLabel} /></InspectorField>
        <InspectorField label="Background color"><InspectorTokenControl label={state.tokenBackgroundColor} onClick={() => controller.requestAction("token-picker:button-background")} swatch="#00F59B" /></InspectorField>
        <InspectorField label="Text color"><InspectorTokenControl label={state.tokenTextColor} onClick={() => controller.requestAction("token-picker:button-text")} swatch="#FFFFFF" /></InspectorField>
      </Section>
      <Section id="layout" label="Layout" open={state.openSections.layout} toggle={() => toggleSection("layout")}>
        <InspectorField label="Padding"><PaddingControls onChange={(side, value) => setNestedValue("padding", side, value)} values={state.padding} /></InspectorField>
      </Section>
      <Section id="layers" label="Layers" open={state.openSections.layers} toggle={() => toggleSection("layers")}>
        <AdLayers onSelectionChange={onSelectionChange} selected="button" />
      </Section>
    </>
  );
}

export function ImageInspector({
  onSelectionChange,
  selection,
}: {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  selection: ChatShellInspectorSelection;
}) {
  const headerController = useInspectorController([], selection);
  const title = selection === "canvas" ? "Canvas" : selection === "text" ? "Text34" : selection === "button" ? "Button" : "Image1";

  return (
    <aside aria-label="Ad inspector" className={styles.inspector}>
      <div className={styles.inspectorRail}>
        <InspectorHeader
          elementActions={selection !== "canvas"}
          locked={headerController.state.locked}
          onLockToggle={() => headerController.setValue("locked", !headerController.state.locked)}
          onVisibilityToggle={() => headerController.setValue("visible", !headerController.state.visible)}
          title={title}
          visible={headerController.state.visible}
        />
        {selection === "canvas" ? <AdCanvasInspector onSelectionChange={onSelectionChange} /> : null}
        {selection === "text" ? <AdTextInspector onSelectionChange={onSelectionChange} /> : null}
        {selection === "image" ? <AdImageInspector onSelectionChange={onSelectionChange} /> : null}
        {selection === "button" ? <AdButtonInspector onSelectionChange={onSelectionChange} /> : null}
        {!(["button", "canvas", "image", "text"] as ChatShellInspectorSelection[]).includes(selection) ? <AdCanvasInspector onSelectionChange={onSelectionChange} /> : null}
      </div>
    </aside>
  );
}
