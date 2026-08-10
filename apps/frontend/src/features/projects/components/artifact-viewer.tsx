import Image from "next/image";
import { projectCanvasFontFamilies } from "../config/project-canvas-fonts";
import type {
  InspectorSelection,
  PreviewDevice,
  ProjectArtifact,
  ProjectTableContent,
  ProjectWebsiteContent,
} from "../model/project-workspace";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

function WebsiteCanvas({
  content,
  ctaLabel,
  headline,
  headlineAlign,
  headlineColor,
  headlineFont,
  headlineSize,
  headlineWeight,
  heroImageFit,
  heroImagePath,
  heroImageRadius,
  onSelect,
}: {
  content: ProjectWebsiteContent;
  ctaLabel: string;
  headline: string;
  headlineAlign: "left" | "center" | "right";
  headlineColor: string;
  headlineFont: "Arial" | "Inter" | "Satoshi";
  headlineSize: number;
  headlineWeight: 400 | 500 | 600;
  heroImageFit: "fill" | "fit";
  heroImagePath: string;
  heroImageRadius: number;
  onSelect: (selection: InspectorSelection) => void;
}) {
  return (
    <div className={styles.websiteCanvas}>
      <nav>
        <Image alt={content.brandAlt} height={24} src={content.brandLogoPath} width={98} />
        <span>{content.navItems.map((item) => <a key={item}>{item}</a>)}</span>
        <button onClick={() => onSelect("button")} type="button">{ctaLabel}</button>
      </nav>
      <main>
        <span className={styles.partnerBadge}>{content.badge}</span>
        <button
          className={styles.editableHeadline}
          onClick={() => onSelect("text")}
          style={{ color: headlineColor, fontFamily: projectCanvasFontFamilies[headlineFont], fontSize: headlineSize, fontWeight: headlineWeight, textAlign: headlineAlign }}
          type="button"
        >
          {headline.split("\n").map((line) => <span key={line}>{line}</span>)}
        </button>
        <p>{content.subheading}</p>
        <button className={styles.websiteHeroImage} onClick={() => onSelect("image")} style={{ borderRadius: heroImageRadius }} type="button">
          <Image alt={content.heroAlt} fill loading="eager" sizes="800px" src={heroImagePath} style={{ objectFit: heroImageFit === "fill" ? "fill" : "contain" }} unoptimized={heroImagePath.startsWith("blob:")} />
        </button>
      </main>
    </div>
  );
}

function TableArtifact({ content }: { content: ProjectTableContent }) {
  return (
    <div className={styles.generatedTable}>
      <header><strong>{content.title}</strong><button type="button">{content.actionLabel}</button></header>
      <div className={styles.generatedTableRow} data-header="true">{content.columns.map((column) => <span key={column}>{column}</span>)}</div>
      {content.rows.map((row) => (
        <div className={styles.generatedTableRow} key={row.company}>
          <span><Image alt="" height={18} src={row.logoPath} width={18} />{row.company}</span>
          <span>{row.contact}</span>
          <span><i>{row.tier}</i></span>
          <span>{row.status}</span>
        </div>
      ))}
    </div>
  );
}

function CanvasArtifact({ artifact }: { artifact: ProjectArtifact }) {
  return (
    <div className={styles.canvasBoard}>
      {(artifact.canvasPagePaths ?? [artifact.imagePath]).map((src, index) => (
        <div className={styles.canvasPage} key={`${src}-${index}`}>
          <Image alt="" fill sizes="360px" src={src} />
        </div>
      ))}
    </div>
  );
}

export function ArtifactViewer({
  artifact,
  ctaLabel,
  headline,
  headlineAlign,
  headlineColor,
  headlineFont,
  headlineSize,
  headlineWeight,
  heroImageFit,
  heroImagePath,
  heroImageRadius,
  inspectorOpen,
  inspectorSelection,
  onHeadlineAlignChange,
  onHeadlineColorChange,
  onHeadlineFontChange,
  onHeadlineSizeChange,
  onHeadlineWeightChange,
  onPreviewDeviceChange,
  onPreviewZoomChange,
  onSelect,
  previewDevice,
  previewZoom,
}: {
  artifact: ProjectArtifact;
  ctaLabel: string;
  headline: string;
  headlineAlign: "left" | "center" | "right";
  headlineColor: string;
  headlineFont: "Arial" | "Inter" | "Satoshi";
  headlineSize: number;
  headlineWeight: 400 | 500 | 600;
  heroImageFit: "fill" | "fit";
  heroImagePath: string;
  heroImageRadius: number;
  inspectorOpen: boolean;
  inspectorSelection: InspectorSelection;
  onHeadlineAlignChange: (alignment: "left" | "center" | "right") => void;
  onHeadlineColorChange: (color: string) => void;
  onHeadlineFontChange: (font: "Arial" | "Inter" | "Satoshi") => void;
  onHeadlineSizeChange: (size: number) => void;
  onHeadlineWeightChange: (weight: 400 | 500 | 600) => void;
  onPreviewDeviceChange: () => void;
  onPreviewZoomChange: (zoom: number) => void;
  onSelect: (selection: InspectorSelection) => void;
  previewDevice: PreviewDevice;
  previewZoom: number;
}) {
  return (
    <section className={styles.artifactViewer}>
      <header className={styles.artifactToolbar}>
        <span><ProjectIcon name={artifact.type === "website" ? "globe" : artifact.type === "table" ? "target-accounts" : "edit"} size={12} />{artifact.viewerTitle ?? artifact.title}</span>
        <div>
          {artifact.type === "website" ? <button aria-label={`Preview device: ${previewDevice}`} className={styles.deviceButton} onClick={onPreviewDeviceChange} type="button"><ProjectIcon name="laptop" size={18} /><ProjectIcon name="chevrons-up-down" size={8} /></button> : null}
          <label className={styles.zoomSelect}>
            <select aria-label="Preview zoom" onChange={(event) => onPreviewZoomChange(Number(event.target.value))} value={previewZoom}>
              <option value="50">50%</option>
              <option value="75">75%</option>
              <option value="100">100%</option>
            </select>
            <ProjectIcon name="chevron-down" size={12} />
          </label>
          <a className={styles.exportButton} download href={artifact.imagePath}>Export</a>
        </div>
      </header>
      <div className={styles.artifactStage} data-device={previewDevice} data-zoom={previewZoom}>
        {artifact.type === "website" && artifact.websiteContent ? (
          <div className={styles.websiteCanvasFrame}>
            {inspectorOpen && inspectorSelection === "text" ? (
              <div className={styles.canvasTextToolbar}>
                <label aria-label="Text color"><input onChange={(event) => onHeadlineColorChange(event.target.value)} type="color" value={headlineColor} /></label>
                <button onClick={() => onHeadlineFontChange(headlineFont === "Inter" ? "Satoshi" : "Inter")} type="button">{headlineFont}<ProjectIcon name="chevron-down" size={10} /></button>
                <label><input aria-label="Text size" min="10" onChange={(event) => onHeadlineSizeChange(Number(event.target.value) * 2)} type="number" value={Math.round(headlineSize / 2)} /><ProjectIcon name="chevron-down" size={10} /></label>
                <button onClick={() => onHeadlineWeightChange(headlineWeight === 600 ? 400 : 600)} type="button">{headlineWeight === 600 ? "Bold" : "Regular"}<ProjectIcon name="chevron-down" size={10} /></button>
                <span>{(["left", "center", "right"] as const).map((align) => <button aria-label={`Align ${align}`} aria-pressed={headlineAlign === align} key={align} onClick={() => onHeadlineAlignChange(align)} type="button"><ProjectIcon name={align === "left" ? "align-left" : align === "center" ? "align-center" : "align-right"} size={12} /></button>)}</span>
                <button type="button"><ProjectIcon name="sparkles" size={12} />Ask agent</button>
              </div>
            ) : null}
            {inspectorOpen && inspectorSelection === "text" ? <span className={styles.canvasSelectionOutline} /> : null}
            <WebsiteCanvas
              content={artifact.websiteContent}
              ctaLabel={ctaLabel}
              headline={headline}
              headlineAlign={headlineAlign}
              headlineColor={headlineColor}
              headlineFont={headlineFont}
              headlineSize={headlineSize}
              headlineWeight={headlineWeight}
              heroImageFit={heroImageFit}
              heroImagePath={heroImagePath}
              heroImageRadius={heroImageRadius}
              onSelect={onSelect}
            />
          </div>
        ) : artifact.type === "table" && artifact.tableContent ? <TableArtifact content={artifact.tableContent} /> : <CanvasArtifact artifact={artifact} />}
      </div>
    </section>
  );
}
