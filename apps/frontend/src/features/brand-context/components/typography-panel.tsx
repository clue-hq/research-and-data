import type { ChangeEvent } from "react";
import type { BrandContextController } from "../hooks/use-brand-context-controller";
import { TypefaceSample } from "./typeface-sample";
import { BrandContextIcon } from "./brand-context-icon";
import styles from "./brand-context.module.css";

export function TypographyPanel({
  controller,
  emptyMessage,
}: {
  controller: BrandContextController;
  emptyMessage: string;
}) {
  const empty = !controller.typefaces.length && !controller.textStyles.length;
  return (
    <div className={styles.typographyPanel}>
      {empty ? <div className={styles.emptyState}>{emptyMessage}</div> : null}
      {!empty ? (
        <>
          <section className={styles.typographySection}>
            <div className={styles.sectionTitleRow}>
              <h2>Typefaces</h2>
              <button className={styles.secondaryButton} onClick={controller.openNewTypefaceDialog} type="button">+ New typeface</button>
            </div>
            <div className={styles.typefaceList}>
              {controller.typefaces.map((typeface) => (
                <article className={styles.typefaceRow} key={typeface.id}>
                  <div className={styles.typefaceName}>
                    <span>{typeface.family}</span>
                    {typeface.source === "custom" ? <small>Custom</small> : null}
                  </div>
                  <TypefaceSample typeface={typeface} />
                  <button
                    aria-expanded={controller.typefaceMenuId === typeface.id}
                    aria-label={`${typeface.family} actions`}
                    className={styles.typefaceMenuButton}
                    onClick={() => controller.toggleTypefaceMenu(typeface.id)}
                    type="button"
                  >
                    <BrandContextIcon name="more" size={14} />
                  </button>
                  {controller.typefaceMenuId === typeface.id ? (
                    <div className={styles.typefaceMenu} role="menu">
                      <button onClick={() => controller.useTypefaceInNewStyle(typeface.id)} role="menuitem" type="button">Use in new style</button>
                      {typeface.source === "custom" ? (
                        <button className={styles.typefaceMenuDanger} onClick={() => controller.removeTypeface(typeface.id)} role="menuitem" type="button">Remove typeface</button>
                      ) : (
                        <span>Library typeface</span>
                      )}
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          </section>

          <section className={styles.typographySection}>
            <div className={styles.sectionTitleRow}>
              <h2>Text styles</h2>
              <button className={styles.secondaryButton} onClick={controller.openNewStyleDialog} type="button">+ New style</button>
            </div>
            <div className={styles.textStyleTable} role="table">
              <div className={styles.textStyleHeader} role="row">
                <span role="columnheader">Text style</span>
                <span role="columnheader">Typeface</span>
                <span role="columnheader">Size</span>
                <span role="columnheader">Font-weight</span>
                <span role="columnheader">Line-height</span>
                <span role="columnheader">Recommended use</span>
                <span aria-hidden="true" />
              </div>
              {controller.textStyles.map((style) => (
                <div className={styles.textStyleRow} key={style.id} role="row">
                  <span role="cell"><span className={styles.stylePill}>{style.name.toLocaleLowerCase()}</span></span>
                  <span role="cell">{style.fontFamily}</span>
                  <span role="cell">{style.fontSize}px</span>
                  <span role="cell">{style.fontWeight}</span>
                  <span role="cell">{style.lineHeight}px</span>
                  <span role="cell">{style.recommendedUse}</span>
                  <button aria-label={`${style.name} style actions`} className={styles.textStyleMenuButton} role="cell" type="button">
                    <BrandContextIcon name="more" size={14} />
                  </button>
                </div>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

function DialogShell({
  children,
  onClose,
  title,
}: {
  children: React.ReactNode;
  onClose: () => void;
  title: string;
}) {
  return (
    <div
      className={styles.dialogBackdrop}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      role="presentation"
    >
      <section aria-label={title} aria-modal="true" className={`${styles.formDialog} clue-panel-enter`} role="dialog">
        <div className={styles.formDialogHeader}>
          <h2>{title}</h2>
          <button aria-label={`Close ${title}`} className={styles.iconButton} onClick={onClose} type="button"><BrandContextIcon name="close" size={16} /></button>
        </div>
        {children}
      </section>
    </div>
  );
}

export function NewTypefaceDialog({ controller }: { controller: BrandContextController }) {
  if (controller.dialog !== "new-typeface") return null;

  function onFontFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) controller.addCustomFont(file);
  }

  return (
    <DialogShell onClose={controller.closeDialog} title="New typeface">
      <div className={styles.formDialogBody}>
        <label className={styles.formField}>
          <span>Font</span>
          <div className={styles.dialogSearchField}>
            <BrandContextIcon name="search" size={14} />
            <input onChange={(event) => controller.setFontSearch(event.target.value)} placeholder="Search fonts" value={controller.fontSearch} />
          </div>
        </label>
        {controller.fontSearch ? (
          <div className={styles.fontResults}>
            {controller.filteredTypefaces.map((typeface) => <button key={typeface.id} onClick={() => controller.setFontSearch(typeface.family)} type="button">{typeface.family}</button>)}
            {!controller.filteredTypefaces.length ? <p>No library font found.</p> : null}
          </div>
        ) : null}
        <div className={styles.customFontUpload}>
          <div>
            <strong>Can’t find the font?</strong>
            <span>Upload an OTF, TTF, WOFF, or WOFF2 file.</span>
          </div>
          <label className={styles.uploadButton}>
            <BrandContextIcon name="upload" size={14} />
            <span>{controller.customFontName || "Upload font"}</span>
            <input accept=".otf,.ttf,.woff,.woff2,font/otf,font/ttf,font/woff,font/woff2" onChange={onFontFile} type="file" />
          </label>
        </div>
      </div>
      <div className={styles.formDialogFooter}>
        <button className={styles.tertiaryButton} onClick={controller.closeDialog} type="button">Cancel</button>
        <button className={styles.primaryButton} disabled={!controller.fontSearch.trim() && !controller.customFontName} onClick={controller.createTypeface} type="button">Create</button>
      </div>
    </DialogShell>
  );
}

export function NewStyleDialog({ controller }: { controller: BrandContextController }) {
  if (controller.dialog !== "new-style") return null;

  return (
    <DialogShell onClose={controller.closeDialog} title="New style">
      <div className={styles.formDialogBody}>
        <label className={styles.formField}><span>Style name</span><input onChange={(event) => controller.setNewStyle("name", event.target.value)} value={controller.newStyle.name} /></label>
        <label className={styles.formField}><span>Font</span><select onChange={(event) => controller.setNewStyle("fontFamily", event.target.value)} value={controller.newStyle.fontFamily}>{controller.typefaces.map((typeface) => <option key={typeface.id}>{typeface.family}</option>)}</select></label>
        <div className={styles.inlineFields}>
          <label className={styles.formField}><span>Size</span><input min="8" onChange={(event) => controller.setNewStyle("fontSize", Number(event.target.value))} type="number" value={controller.newStyle.fontSize} /></label>
          <label className={styles.formField}><span>Weight</span><select onChange={(event) => controller.setNewStyle("fontWeight", Number(event.target.value))} value={controller.newStyle.fontWeight}><option value="400">400</option><option value="500">500</option><option value="600">600</option><option value="700">700</option></select></label>
          <label className={styles.formField}><span>Line-height</span><input min="8" onChange={(event) => controller.setNewStyle("lineHeight", Number(event.target.value))} type="number" value={controller.newStyle.lineHeight} /></label>
        </div>
        <label className={styles.formField}><span>Recommended use <em>(Optional)</em></span><input onChange={(event) => controller.setNewStyle("recommendedUse", event.target.value)} value={controller.newStyle.recommendedUse} /></label>
      </div>
      <div className={styles.formDialogFooter}>
        <button className={styles.tertiaryButton} onClick={controller.closeDialog} type="button">Cancel</button>
        <button className={styles.primaryButton} onClick={controller.createTextStyle} type="button">Create style</button>
      </div>
    </DialogShell>
  );
}
