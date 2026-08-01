import React from "react";

/** The approval pill (approved / draft) shared by the list card and the detail
 * header. Draft uses the accent-wash "needs review" tone; approved the success
 * wash — both from brand.css `.status-pill` variants. */
export function ApprovalPill({ status }: { status: string | null }): React.ReactElement {
  const approved = status === "approved";
  return (
    <span className={`status-pill ${approved ? "is-approved" : "is-draft"}`}>
      {approved ? "Approved" : "Draft"}
    </span>
  );
}

/** Structural readiness is the EXPECTED state (the normalizer backfills every
 * required token), so a proud "Product ready" pill on an unreviewed draft is
 * noise at best and misleading at worst. Surface only the exception: a kit
 * with missing pieces gets a warning pill; a complete kit gets nothing. */
export function KitReadinessPill({ ready }: { ready: boolean }): React.ReactElement | null {
  if (ready) return null;
  return <span className="status-pill is-error">Incomplete</span>;
}
