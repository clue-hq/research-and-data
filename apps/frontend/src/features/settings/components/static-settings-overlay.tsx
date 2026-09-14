import type { ReactNode } from "react";
import { Clock3 } from "lucide-react";
import styles from "./settings.module.css";
export function StaticSettingsOverlay({ children }: { children: ReactNode }) {
  return (
    <section
      aria-labelledby="settings-coming-soon-title"
      className={styles.comingSoon}
    >
      <div aria-hidden="true" className={styles.comingSoonPreview} inert>
        <div className={styles.settingsBody}>{children}</div>
      </div>
      <div className={styles.comingSoonOverlay}>
        <div className={styles.comingSoonCard}>
          <span aria-hidden="true" className={styles.comingSoonIcon}>
            <Clock3 size={25} strokeWidth={1.35} />
          </span>
          <span className={styles.comingSoonBadge}>In development</span>
          <h2 id="settings-coming-soon-title">Coming soon</h2>
          <p>These settings are on the way.</p>
        </div>
      </div>
    </section>
  );
}
