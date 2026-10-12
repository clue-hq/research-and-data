import type { MeasuredBrandView, MotionCard } from "../model/measured-view";
import styles from "./brand-context.module.css";

/** Motion (Wave 2 A9, Task X6): the brand's animations, scroll reveals and the motion pages made
 * here do not copy, each as a typeface card with its timing in words (no live preview: DR-A9-6). */
export function MotionPanel({ measured }: { measured: MeasuredBrandView | null }) {
  const sections: { id: string; title: string; cards: readonly MotionCard[] }[] = [
    { id: "animations", title: "Animations", cards: measured?.animations ?? [] },
    { id: "reveals", title: "Scroll reveals", cards: measured?.reveals ?? [] },
    { id: "scripted", title: "Scripted motion", cards: measured?.scripted ?? [] },
  ].filter((section) => section.cards.length > 0);
  return (
    <div className={styles.typographyPanel}>
      {!sections.length ? <div className={styles.emptyState}>No measured motion yet.</div> : null}
      {sections.map((section) => (
        <section className={styles.typographySection} key={section.id}>
          <div className={styles.sectionTitleRow}>
            <h2>{section.title}</h2>
          </div>
          <div className={styles.typefaceList}>
            {section.cards.map((card) => (
              <article className={styles.typefaceRow} key={card.id}>
                <div className={styles.typefaceName}>
                  <span>{card.name}</span>
                </div>
                <p>{card.headline}</p>
                {card.lines.map((line) => (
                  <span className={styles.typefacePreviewStatus} key={line}>{line}</span>
                ))}
              </article>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
