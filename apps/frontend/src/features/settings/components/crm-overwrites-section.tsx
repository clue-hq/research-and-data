"use client";

import type { CrmOverwritesView } from "@/features/integrations/model/crm-integration-page";
import type { CrmOverwritesMode } from "@/features/integrations/model/crm-settings";
import styles from "./crm-integration-page.module.css";

/**
 * "Overwrites" (boards 02/03 2309:2007 / 2309:2381); a member reads the mode only (board 07
 * member view 2310:2564). Choosing an option saves it (Follow “Always allow” after its dialog).
 */
export function CrmOverwritesSection({
  view,
  busy,
  error,
  onChoose,
}: {
  view: CrmOverwritesView;
  busy: boolean;
  error: string | null;
  onChoose: (mode: CrmOverwritesMode) => void;
}) {
  return (
    <section className={styles.card} aria-labelledby="crm-overwrites-title">
      <h2 className={styles.cardTitle} id="crm-overwrites-title">
        {view.title}
      </h2>
      {view.editable ? (
        <div className={styles.optionGroup} role="radiogroup" aria-labelledby="crm-overwrites-title">
          {view.description ? <p className={styles.subtle}>{view.description}</p> : null}
          {view.options.map((option) => (
            <label className={styles.option} key={option.mode}>
              <input
                checked={option.selected}
                disabled={busy}
                name="crm-overwrites"
                onChange={() => {
                  if (!option.selected) onChoose(option.mode);
                }}
                type="radio"
                value={option.mode}
              />
              <span className={styles.stack}>
                <span className={styles.label}>{option.label}</span>
                <span className={styles.subtle}>{option.description}</span>
              </span>
            </label>
          ))}
        </div>
      ) : null}
      {error ? (
        <p className={styles.warning} role="alert">
          {error}
        </p>
      ) : null}
      <p className={styles.subtle}>{view.note}</p>
    </section>
  );
}
