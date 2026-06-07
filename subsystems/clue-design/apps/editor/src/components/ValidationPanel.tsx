"use client";

import { Braces, TriangleAlert } from "lucide-react";
import type { Diagnostic, Operation } from "@/engine/contracts";

interface ValidationPanelProps {
  diagnostics: Diagnostic[];
  lastOperation: Operation | null;
}

export function ValidationPanel({ diagnostics, lastOperation }: ValidationPanelProps) {
  return (
    <section className="inspector-section">
      <div className="section-heading">
        <TriangleAlert aria-hidden size={15} />
        Diagnostics
      </div>
      {diagnostics.length === 0 ? (
        <p className="muted">No local diagnostics.</p>
      ) : (
        <ul className="diagnostic-list">
          {diagnostics.map((diagnostic) => (
            <li key={`${diagnostic.code}-${diagnostic.message}`} className={diagnostic.severity}>
              <strong>{diagnostic.code}</strong>
              <span>{diagnostic.message}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="section-heading operation-heading">
        <Braces aria-hidden size={15} />
        Last operation
      </div>
      <pre className="operation-preview">
        {lastOperation ? JSON.stringify(lastOperation, null, 2) : "No operation emitted yet."}
      </pre>
    </section>
  );
}
