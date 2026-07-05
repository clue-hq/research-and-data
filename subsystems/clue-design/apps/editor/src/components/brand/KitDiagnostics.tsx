import React, { useState } from "react";

interface DiagnosticView {
  severity?: string | null;
  code?: string | null;
  message?: string | null;
}

function severityClass(severity: string | null | undefined): string {
  if (severity === "error") return "is-error";
  if (severity === "warning") return "is-warning";
  return "";
}

/** Section 8 — diagnostics collapsed behind a ghost toggle, severity-classed. */
export function KitDiagnostics({
  diagnostics
}: {
  diagnostics: DiagnosticView[];
}): React.ReactElement | null {
  const [open, setOpen] = useState(false);
  if (diagnostics.length === 0) return null;

  return (
    <section className="brand-section" aria-label="Diagnostics">
      <button
        type="button"
        className="btn btn-quiet"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
      >
        {open ? "Hide" : "Show"} {diagnostics.length}{" "}
        {diagnostics.length === 1 ? "diagnostic" : "diagnostics"}
      </button>
      {open ? (
        <ul className="diag-list kit-diag-list">
          {diagnostics.map((diagnostic, index) => (
            <li key={`${diagnostic.code}-${index}`} className={severityClass(diagnostic.severity)}>
              <span className="diag-code">{diagnostic.code ?? "—"}</span>
              <span>{diagnostic.message ?? ""}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
