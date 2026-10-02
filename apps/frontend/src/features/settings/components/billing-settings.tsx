import { Button } from "@/components/ui/button";
import type { StaticSettings } from "../model/settings";
import styles from "./settings.module.css";
import { SectionLead, SettingsCard } from "./settings-primitives";

export function BillingSettings({
  billing,
}: {
  billing: StaticSettings["billing"];
}) {
  const spent = billing.totalCredits - billing.remainingCredits;
  const remainingPercent = `${(billing.remainingCredits / billing.totalCredits) * 100}%`;

  return (
    <div className={styles.sectionStack}>
      <section className={styles.connectionSection}>
        <SectionLead>Your plan</SectionLead>
        <SettingsCard className={styles.planCard}>
          <div>
            <p className={styles.planName}>{billing.planName}</p>
            <p className={styles.mutedText}>{billing.planDescription}</p>
          </div>
          <Button size="sm" variant="secondary">
            Manage plan
          </Button>
        </SettingsCard>
      </section>
      <section className={styles.connectionSection}>
        <SectionLead>Credits</SectionLead>
        <SettingsCard className={styles.creditsCard}>
          <div className={styles.creditsHeader}>
            <p className={styles.planName}>
              {billing.remainingCredits} / {billing.totalCredits} remaining
            </p>
            <Button size="sm" variant="secondary">
              Top up credits
            </Button>
          </div>
          <div className={styles.creditBar}>
            <span style={{ width: remainingPercent }} />
          </div>
          <div className={styles.creditLegend}>
            <span>
              <i className={styles.remainingDot} />
              Remaining credits
            </span>
            <span>
              <i className={styles.spentDot} />
              {spent} credits spent
            </span>
          </div>
        </SettingsCard>
      </section>
    </div>
  );
}
