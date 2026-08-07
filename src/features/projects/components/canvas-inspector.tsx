import type { InspectorSelection } from "../model/project-workspace";
import type { ReactNode } from "react";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

const alignmentIcons = {
  center: "align-center",
  left: "align-left",
  right: "align-right",
} as const;

function InspectorSection({
  children,
  collapsed = false,
  label,
}: {
  children?: ReactNode;
  collapsed?: boolean;
  label: string;
}) {
  return (
    <section className={styles.inspectorSection}>
      <button type="button">{label}<ProjectIcon name="chevron-down" size={12} /></button>
      {!collapsed ? children : null}
    </section>
  );
}

function Layers({ selection }: { selection: InspectorSelection }) {
  return (
    <div className={styles.layersTree}>
      <span data-active={selection === "text"}><ProjectIcon name="text" size={14} />Text</span>
      <span><ProjectIcon name="text" size={14} />Text</span>
      <span><ProjectIcon name="layers" size={14} />Group</span>
      <span className={styles.layerChild} data-active={selection === "button"}><ProjectIcon name="text" size={14} />Text</span>
      <span className={styles.layerChild} data-active={selection === "image"}><ProjectIcon name="rectangle" size={14} />Rectangle</span>
    </div>
  );
}

export function CanvasInspector({
  ctaLabel,
  headlineAlign,
  headlineFont,
  headlineSize,
  headlineWeight,
  heroImageFit,
  heroImageRadius,
  onCtaLabelChange,
  onHeadlineAlignChange,
  onHeadlineColorChange,
  onHeadlineFontChange,
  onHeadlineSizeChange,
  onHeadlineWeightChange,
  onHeroImageFitChange,
  onHeroImageRadiusChange,
  onHeroImageReplace,
  selection,
}: {
  ctaLabel: string;
  headlineAlign: "left" | "center" | "right";
  headlineFont: "Arial" | "Inter" | "Satoshi";
  headlineSize: number;
  headlineWeight: 400 | 500 | 600;
  heroImageFit: "fill" | "fit";
  heroImageRadius: number;
  onCtaLabelChange: (label: string) => void;
  onHeadlineAlignChange: (alignment: "left" | "center" | "right") => void;
  onHeadlineColorChange: (color: string) => void;
  onHeadlineFontChange: (font: "Arial" | "Inter" | "Satoshi") => void;
  onHeadlineSizeChange: (size: number) => void;
  onHeadlineWeightChange: (weight: 400 | 500 | 600) => void;
  onHeroImageFitChange: (mode: "fill" | "fit") => void;
  onHeroImageRadiusChange: (radius: number) => void;
  onHeroImageReplace: (file: File) => void;
  selection: InspectorSelection;
}) {
  return (
    <aside className={styles.inspector}>
      <header className={styles.inspectorHeader}>
        <strong>{selection === "canvas" ? "Canvas" : selection[0].toUpperCase() + selection.slice(1)}</strong>
        <span>
          {selection !== "canvas" ? <button aria-label="Lock layer" type="button"><ProjectIcon name="lock" size={12} /></button> : null}
          {selection !== "canvas" ? <button aria-label="Toggle visibility" type="button"><ProjectIcon name="visibility" size={12} /></button> : null}
          <button aria-label="More" type="button"><ProjectIcon name="more" size={12} /></button>
        </span>
      </header>
      {selection === "canvas" ? (
        <InspectorSection label="Background">
          <label className={styles.colorField}>
            <input aria-label="Canvas background color" type="color" value="#00F59B" readOnly />
            <span>#00F59B</span><small>100%</small>
          </label>
        </InspectorSection>
      ) : null}
      {selection !== "canvas" ? <InspectorSection collapsed label="Link to" /> : null}
      {selection === "text" ? (
        <InspectorSection label="Typography">
          <div className={styles.inspectorFields}>
            <label>Color<span className={styles.colorField}><input aria-label="Text color" defaultValue="#00F59B" onChange={(event) => onHeadlineColorChange(event.target.value)} type="color" /><span>#00F59B</span><small>100%</small></span></label>
            <label>Font<select onChange={(event) => onHeadlineFontChange(event.target.value as "Arial" | "Inter" | "Satoshi")} value={headlineFont}><option>Inter</option><option>Satoshi</option><option>Arial</option></select></label>
            <div><label>Size<input min="20" onChange={(event) => onHeadlineSizeChange(Number(event.target.value))} type="number" value={headlineSize} /></label><label>Weight<select onChange={(event) => onHeadlineWeightChange(Number(event.target.value) as 400 | 500 | 600)} value={headlineWeight}><option value="400">Regular</option><option value="500">Medium</option><option value="600">Semi Bold</option></select></label></div>
            <label>Alignment<span className={styles.alignmentControls}><span className={styles.segmented}>{(["left", "center", "right"] as const).map((align) => <button aria-label={`Align ${align}`} aria-pressed={headlineAlign === align} key={align} onClick={() => onHeadlineAlignChange(align)} type="button"><ProjectIcon name={alignmentIcons[align]} size={12} /></button>)}</span><span className={`${styles.segmented} ${styles.verticalSegmented}`}><button aria-label="Align to top" aria-pressed="true" type="button"><ProjectIcon name="align-vertical-start" size={12} /></button><button aria-label="Distribute vertically" type="button"><ProjectIcon name="align-vertical-around" size={12} /></button><button aria-label="Align to bottom" type="button"><ProjectIcon name="align-vertical-end" size={12} /></button></span></span></label>
          </div>
        </InspectorSection>
      ) : null}
      {selection === "image" ? (
        <InspectorSection label="Fill">
          <div className={styles.imageReplace}><span>Image</span><label>Replace image<input accept="image/*" onChange={(event) => { const file = event.target.files?.[0]; if (file) onHeroImageReplace(file); }} type="file" /></label></div>
          <label className={styles.fullField}>Mode<select onChange={(event) => onHeroImageFitChange(event.target.value.toLocaleLowerCase() as "fill" | "fit")} value={heroImageFit === "fill" ? "Fill" : "Fit"}><option>Fill</option><option>Fit</option></select></label>
          <label className={styles.fullField}>Radius<input min="0" onChange={(event) => onHeroImageRadiusChange(Number(event.target.value))} type="number" value={heroImageRadius} /></label>
        </InspectorSection>
      ) : null}
      {selection === "button" ? (
        <>
          <InspectorSection label="Style"><div className={styles.inspectorFields}><label>Label<input onChange={(event) => onCtaLabelChange(event.target.value)} value={ctaLabel} /></label><label>Background<span className={styles.colorField}><input type="color" defaultValue="#32362D" /><span>#32362D</span><small>100%</small></span></label></div></InspectorSection>
          <InspectorSection label="Layout"><div className={styles.fourFields}><input defaultValue="8" /><input defaultValue="12" /><input defaultValue="8" /><input defaultValue="12" /></div></InspectorSection>
        </>
      ) : null}
      {selection === "text" ? <><InspectorSection collapsed label="Stroke" /><InspectorSection collapsed label="Layout" /></> : null}
      <InspectorSection label="Layers"><Layers selection={selection} /></InspectorSection>
    </aside>
  );
}
