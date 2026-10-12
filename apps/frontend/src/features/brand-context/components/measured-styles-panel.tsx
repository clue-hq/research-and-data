import { Fragment } from "react";
import type { BrandTypeface } from "../model/brand-context";
import {
  typefaceFor,
  type MeasuredBrandView,
  type MeasuredStyleView,
  type MeasuredValue,
} from "../model/measured-view";
import { StyleSample } from "./style-sample";
import styles from "./brand-context.module.css";

/**
 * Components (Wave 2 A9, Task X6): each measured button, card and link style of the seller's site,
 * one card per state, side by side. Built from the Typography panel's section and typeface-card
 * classes, the asset grid's preview box and the colour swatch's name-and-value pair (DR-A9-2…4).
 */
export function MeasuredStylesPanel({
  measured,
  typefaces,
}: {
  measured: MeasuredBrandView | null;
  typefaces: readonly BrandTypeface[];
}) {
  const groups = measured?.groups ?? [];
  return (
    <div className={styles.typographyPanel}>
      {!groups.length ? <div className={styles.emptyState}>No measured styles yet.</div> : null}
      {groups.map((group) => (
        <section className={styles.typographySection} key={group.id}>
          <div className={styles.sectionTitleRow}>
            <h2>{group.title}</h2>
          </div>
          {group.styles.map((style) => (
            <MeasuredStyle key={style.id} style={style} typeface={typefaceFor(typefaces, style.family)} />
          ))}
        </section>
      ))}
    </div>
  );
}

function MeasuredStyle({ style, typeface }: { style: MeasuredStyleView; typeface: BrandTypeface | null }) {
  return (
    <div className={styles.typographySection}>
      <div className={styles.typefaceName}>
        <span>{style.name}</span>
        <small>{style.variant}</small>
      </div>
      <div className={styles.typefaceList}>
        {style.samples.map((sample) => (
          <article className={styles.typefaceRow} key={sample.state}>
            <div className={styles.typefaceName}>
              <span>{sample.name}</span>
            </div>
            <div className={styles.assetCardPreview} style={sample.backdrop ? { background: sample.backdrop } : undefined}>
              <StyleSample sample={sample} typeface={typeface} word={style.word} />
            </div>
            {sample.note ? <span className={styles.typefacePreviewStatus}>{sample.note}</span> : null}
            <MeasuredValues values={sample.values} />
          </article>
        ))}
      </div>
      <MeasuredValues values={style.transitions} />
    </div>
  );
}

export function MeasuredValues({ values }: { values: readonly MeasuredValue[] }) {
  if (!values.length) return null;
  return (
    <div className={styles.swatchMeta}>
      {values.map((value, index) => (
        <Fragment key={`${value.part}-${index}`}>
          <span className={styles.swatchLabel}>{value.label}</span>
          <code>{`${value.value} (${value.token})`}</code>
        </Fragment>
      ))}
    </div>
  );
}
