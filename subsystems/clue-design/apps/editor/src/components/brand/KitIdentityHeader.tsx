import React from "react";

import type { BrandKitListEntry } from "@/engine/brandHub";
import { ApprovalPill, KitReadinessPill } from "./KitStatusPills";

interface KitIdentityHeaderProps {
  kit: BrandKitListEntry;
  sourceUrl: string | null;
  capturedAt: string | null;
  /** Optimistic approval state — driven by the page, not this component. */
  approved: boolean;
  approveBusy: boolean;
  approveError: string | null;
  onToggleApproval: () => void;
}

/** Section 1 — the identity header: display name with a terminal period,
 * source/url/captured line, status pills, the kit description, and the action
 * row (Approve / Revert to draft + Open editor). All workflow lives in the
 * page; this component only binds fields and fires the callback. */
export function KitIdentityHeader({
  kit,
  sourceUrl,
  capturedAt,
  approved,
  approveBusy,
  approveError,
  onToggleApproval
}: KitIdentityHeaderProps): React.ReactElement {
  const sourceParts = [kit.source, sourceUrl, capturedAt ? `captured ${capturedAt}` : null]
    .filter((part): part is string => Boolean(part))
    .join(" · ");

  return (
    <header className="kit-identity">
      <h1 className="display kit-identity-name">{`${kit.name}.`}</h1>
      {sourceParts ? <p className="caption mono kit-identity-source">{sourceParts}</p> : null}
      <div className="kit-pill-row">
        <ApprovalPill status={approved ? "approved" : "draft"} />
        <KitReadinessPill ready={kit.product_ready} />
      </div>
      {kit.description ? <p className="kit-identity-desc">{kit.description}</p> : null}
      <div className="kit-action-row">
        <button
          type="button"
          className={`btn ${approved ? "btn-ghost" : "btn-primary"}`}
          onClick={onToggleApproval}
          disabled={approveBusy}
        >
          {approved ? "Revert to draft" : "Approve"}
        </button>
        <a className="btn btn-ghost" href="/">
          Open editor
        </a>
        {approveError ? (
          <span className="status-pill is-error kit-inline-error">{approveError}</span>
        ) : null}
      </div>
    </header>
  );
}
