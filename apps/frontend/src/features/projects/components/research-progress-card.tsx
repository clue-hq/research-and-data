"use client";

import type { ResearchProgress } from "../model/research-progress";
import { ProjectIcon } from "./project-icon";
import styles from "./research-progress-card.module.css";

const PILL_LABEL = {
  running: "Running",
  completed: "Completed",
  needs_attention: "Needs attention",
} as const;

export function ResearchProgressCard({
  card,
  headline,
  line,
}: {
  card: ResearchProgress;
  headline: string;
  line: string;
}) {
  return (
    <section aria-label="Account research progress" className={styles.card}>
      <header className={styles.header}>
        <ProjectIcon className={styles.glyph} name="telescope" size={16} />
        <div className={styles.titles}>
          <h2 className={styles.title}>Account research</h2>
          <p className={styles.subtitle}>{headline}</p>
        </div>
        <span className={styles.pill} data-pill={card.pill}>
          {PILL_LABEL[card.pill]}
        </span>
      </header>
      <div className={styles.queuedRow}>
        <span aria-hidden="true" className={styles.queuedDot} />
        <span className={styles.queuedCount}>
          {card.queued} {card.queued === 1 ? "Account" : "Accounts"}
        </span>
        <span className={styles.queuedLabel}>Queued</span>
      </div>
      <div
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={card.progress_pct}
        className={styles.bar}
        role="progressbar"
      >
        <span className={styles.barFill} style={{ width: `${card.progress_pct}%` }} />
      </div>
      <p className={styles.line}>{line}</p>
    </section>
  );
}
