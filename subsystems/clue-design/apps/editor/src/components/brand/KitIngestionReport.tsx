import React from "react";

import { KitSwatch } from "./KitSwatch";
import { readRoleAssignments, readStringList, type RoleAssignment } from "./kitJson";

function BasisCell({ basis }: { basis: string | null }): React.ReactElement {
  const value = (basis ?? "").toLowerCase();
  if (value === "evidence") {
    return <span className="status-pill is-approved">evidence</span>;
  }
  if (value === "default") {
    return <span className="status-pill is-draft">default</span>;
  }
  return <span className="chip">{basis ?? "derived"}</span>;
}

function isColorAssignment(row: RoleAssignment): boolean {
  return typeof row.value === "string" && /^#[0-9a-fA-F]{3,8}$/.test(row.value.trim());
}

/** Section 7 — the ingestion report: stats line, gap chips, and the
 * role-assignments table (token / swatch+hex / basis / pointer). */
export function KitIngestionReport({
  ingestionReport
}: {
  ingestionReport: Record<string, any> | null;
}): React.ReactElement | null {
  if (!ingestionReport) return null;
  const stats =
    ingestionReport.stats && typeof ingestionReport.stats === "object"
      ? (ingestionReport.stats as Record<string, unknown>)
      : {};
  const gaps = readStringList(ingestionReport.gaps);
  const assignments = readRoleAssignments(ingestionReport);
  const statsLine = Object.entries(stats)
    .map(([key, value]) => `${value} ${key.replace(/_/g, " ")}`)
    .join(" · ");

  return (
    <section className="brand-section" aria-label="Ingestion report">
      <div className="brand-section-head">
        <span className="title">Ingestion report</span>
      </div>
      <div className="brand-card kit-ingestion-card">
        {statsLine ? <p className="mono kit-stats-line">{statsLine}</p> : null}
        {gaps.length > 0 ? (
          <div className="kit-gap-chips">
            {gaps.map((gap) => (
              <span className="chip" key={gap}>
                {gap}
              </span>
            ))}
          </div>
        ) : null}
        {assignments.length > 0 ? (
          <table className="brand-table kit-roles-table">
            <thead>
              <tr>
                <th>Token</th>
                <th>Value</th>
                <th>Basis</th>
                <th>Pointer</th>
              </tr>
            </thead>
            <tbody>
              {assignments.map((row, index) => (
                <tr key={`${row.token}-${index}`}>
                  <td className="mono">{row.token}</td>
                  <td>
                    <span className="kit-role-value">
                      {isColorAssignment(row) ? <KitSwatch hex={row.value ?? ""} /> : null}
                      <span className="mono">{row.value ?? "—"}</span>
                    </span>
                  </td>
                  <td>
                    <BasisCell basis={row.basis} />
                  </td>
                  <td className="caption mono kit-role-pointer">{row.pointer ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </div>
    </section>
  );
}
