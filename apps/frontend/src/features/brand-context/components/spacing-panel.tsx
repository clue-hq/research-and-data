import type { MeasuredBrandView } from "../model/measured-view";
import styles from "./brand-context.module.css";

/** Spacing (Wave 2 A9, Task X6): the brand's spacing steps as typeface cards (DR-A9-7). */
export function SpacingPanel({ measured }: { measured: MeasuredBrandView | null }) {
  const steps = measured?.spacing ?? [];
  return (
    <div className={styles.typographyPanel}>
      {!steps.length ? <div className={styles.emptyState}>No measured spacing yet.</div> : (
        <section className={styles.typographySection}>
          <div className={styles.sectionTitleRow}>
            <h2>Spacing</h2>
          </div>
          <div className={styles.typefaceList}>
            {steps.map((step) => (
              <article className={styles.typefaceRow} key={step.id}>
                <div className={styles.typefaceName}>
                  <span>{step.name}</span>
                  {step.measured ? <small>Measured</small> : null}
                </div>
                <p>{step.value}</p>
                <span className={styles.typefacePreviewStatus}>{step.token}</span>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
