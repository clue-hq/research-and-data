"use client";

import { Button } from "@/components/ui/button";
import type { CrmPermissionsView } from "@/features/integrations/model/crm-integration-page";
import styles from "./crm-integration-page.module.css";

/**
 * "Permissions" (boards 02/03 2309:1978 / 2309:2352; board 07 "Permissions / Empty" 2310:2566).
 * Every member may revoke (Global Constraints), so Revoke shows for everyone.
 */
export function CrmPermissionsSection({
  view,
  onRevoke,
}: {
  view: CrmPermissionsView;
  onRevoke: (grantId: string) => void;
}) {
  return (
    <section className={styles.card} aria-labelledby="crm-permissions-title">
      <h2 className={styles.cardTitle} id="crm-permissions-title">
        {view.title}
      </h2>
      {view.rows.length === 0 ? (
        <p className={styles.subtle}>{view.empty}</p>
      ) : (
        <>
          <p className={styles.subtle}>{view.description}</p>
          {view.rows.map((row) => (
            <div className={styles.row} key={row.grantId}>
              <div className={styles.stack}>
                <p className={styles.label}>{row.description}</p>
                <p className={styles.subtle}>{row.meta}</p>
              </div>
              <Button onClick={() => onRevoke(row.grantId)} size="design-sm" variant="transparent">
                Revoke
              </Button>
            </div>
          ))}
        </>
      )}
    </section>
  );
}
