import React from "react";
import Link from "next/link";

import type { BrandKitListEntry } from "@/engine/brandHub";
import { ApprovalPill, KitReadinessPill } from "./KitStatusPills";

function formatDate(value: string | null): string {
  if (!value) return "—";
  // Captured dates arrive as ISO / YYYY-MM-DD strings; show the day only.
  return value.slice(0, 10);
}

/** One kit tile on the /brand list — a clickable tone card (no border, no
 * shadow) that deepens on hover, linking to the review page. The palette strip
 * is the card's identity: without color, every kit reads identically. */
export function KitListCard({
  kit,
  palette
}: {
  kit: BrandKitListEntry;
  palette?: string[];
}): React.ReactElement {
  return (
    <Link
      href={`/brand/kits/${encodeURIComponent(kit.id)}`}
      className="brand-card is-clickable kit-list-card"
      data-testid={`kit-card-${kit.id}`}
    >
      {palette && palette.length > 0 ? (
        <div className="kit-card-palette" aria-hidden>
          {palette.map((hex, index) => (
            <span key={`${hex}-${index}`} style={{ backgroundColor: hex }} />
          ))}
        </div>
      ) : null}
      <div className="kit-card-head">
        <span className="title kit-card-name">{kit.name}</span>
        {kit.source ? <span className="chip">{kit.source}</span> : null}
      </div>
      <div className="kit-pill-row">
        <ApprovalPill status={kit.approval_status} />
        <KitReadinessPill ready={kit.product_ready} />
      </div>
      {kit.description ? <p className="kit-card-desc">{kit.description}</p> : null}
      <p className="caption kit-card-meta">
        <span className="mono">v{kit.version}</span> · captured {formatDate(kit.created_at)}
      </p>
    </Link>
  );
}
