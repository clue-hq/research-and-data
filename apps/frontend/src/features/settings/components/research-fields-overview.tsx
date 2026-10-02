import Link from "next/link";
import { Building2, ContactRound, ChevronRight } from "lucide-react";
import { researchEntities } from "../model/research-fields";
import { SettingsCard } from "./settings-primitives";
import styles from "./settings.module.css";
import researchStyles from "./research-fields.module.css";

export function ResearchFieldsOverview() {
  return (
    <div className={researchStyles.stack}>
      <p className={researchStyles.lead}>Manage what research can find about your accounts and contacts.</p>
      <SettingsCard className={styles.entityList}>
        {researchEntities.map((entity, index) => (
          <div key={entity.id}>
            {index > 0 ? <div className={styles.divider} /> : null}
            <Link className={`${styles.entityRow} ${researchStyles.entityRow}`} href={`/settings/data-model/${entity.id}/fields`} prefetch={false}>
              <span className={styles.entityIcon}>
                {entity.id === "accounts" ? <Building2 size={16} strokeWidth={1.4} /> : <ContactRound size={16} strokeWidth={1.4} />}
              </span>
              <span>{entity.name}<span className={researchStyles.entityDescription}>{entity.description}</span></span>
              <ChevronRight className={styles.entityChevron} size={14} strokeWidth={1.4} />
            </Link>
          </div>
        ))}
      </SettingsCard>
    </div>
  );
}
