"use client";

import Link from "next/link";
import { useState } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { CrmStatusBadge } from "@/features/integrations/components/crm-connect-dialogs";
import type { CrmResearchView } from "@/features/integrations/model/crm-integration-page";
import styles from "./crm-integration-page.module.css";

/**
 * "Research in {CRM}" (board 07 "Research setup / …": 2310:2501, 2310:2518, 2310:2535, 2310:2591,
 * 2338:2403 / 2338:2477, 2338:2427 / 2338:2538; member view 2310:2552). "View details" only
 * opens and closes the read-only explanation (2338:2589).
 */
export function CrmResearchSection({ view }: { view: CrmResearchView }) {
  const [open, setOpen] = useState(false);
  const details = view.details;
  return (
    <section className={`${styles.card} ${styles.researchCard}`} aria-labelledby="crm-research-title">
      <div className={styles.titleRow}>
        <h2 className={styles.cardTitle} id="crm-research-title">
          {view.sectionTitle}
        </h2>
        <CrmStatusBadge tone={view.badge.tone}>{view.badge.label}</CrmStatusBadge>
      </div>
      <p className={styles.label}>{view.title}</p>
      <p className={styles.subtle}>{open ? view.expandedBody : view.body}</p>
      <div className={styles.actions}>
        {view.action ? (
          <Link
            className={buttonVariants({ size: "design-sm", variant: "neutral" })}
            href={view.action.href}
            prefetch={false}
          >
            {view.action.label}
          </Link>
        ) : null}
        <Button
          aria-controls="crm-research-details"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          size="design-sm"
          variant="transparent"
        >
          {open ? view.hideDetailsLabel : view.showDetailsLabel}
        </Button>
      </div>
      {open ? (
        <div className={styles.detailsBody} id="crm-research-details">
          <div className={styles.divider} />
          <p className={styles.label}>{details.heading}</p>
          <p className={styles.subtle}>{details.intro}</p>
          <div className={styles.progress} role="table" aria-label={details.heading}>
            <div className={styles.progressHead} role="row">
              <p role="columnheader">{details.columns.item}</p>
              <p role="columnheader">{details.columns.progress}</p>
            </div>
            {view.rows.map((row) => (
              <div className={styles.progressRow} key={row.key} role="row">
                <div className={styles.stack} role="cell">
                  <p className={styles.label}>{row.title}</p>
                  <p className={styles.subtle}>{row.description}</p>
                </div>
                <p className={row.tone === "warning" ? styles.warning : styles.subtle} role="cell">
                  {row.progress}
                </p>
              </div>
            ))}
          </div>
          {details.blocking ? (
            <>
              <div className={styles.divider} />
              <p className={styles.label}>{details.blocking.heading}</p>
              <p className={styles.warning}>{details.blocking.body}</p>
            </>
          ) : null}
          {details.nextSteps ? (
            <>
              <p className={styles.label}>{details.nextSteps.heading}</p>
              <p className={styles.subtle}>{details.nextSteps.body}</p>
            </>
          ) : null}
          {details.whereToFind ? (
            <>
              <p className={styles.label}>{details.whereToFind.heading}</p>
              <p className={styles.subtle}>{details.whereToFind.body}</p>
            </>
          ) : null}
          {details.footer ? <p className={styles.subtle}>{details.footer}</p> : null}
        </div>
      ) : null}
    </section>
  );
}
