"use client";

import { Braces, Eye, FileCheck2, TriangleAlert } from "lucide-react";
import type { Diagnostic, DiagnosticSubject, NodeId, Operation, PageId, Scene } from "@/engine/contracts";
import type { EditorPreflightResult } from "@/engine/preflightRunner";
import { pageIdForNode } from "@/engine/sceneQueries";

interface ValidationPanelProps {
  scene: Scene;
  activePageId: PageId | null;
  selectedNodeId: NodeId | null;
  diagnostics: Diagnostic[];
  renderDiagnostics?: Diagnostic[];
  lastOperation: Operation | null;
  preflightResult: EditorPreflightResult | null;
  onSelectSubject?: (subject: DiagnosticSubject) => void;
  /** Manual preflight (the old topbar Validate): optional so existing
   * callers/tests without the wiring render without the button. */
  onRunPreflight?: () => void;
  isPreflighting?: boolean;
}

export function ValidationPanel({
  scene,
  activePageId,
  selectedNodeId,
  diagnostics,
  renderDiagnostics = [],
  lastOperation,
  preflightResult,
  onSelectSubject,
  onRunPreflight,
  isPreflighting = false
}: ValidationPanelProps) {
  const focusedDiagnostics = diagnosticsForFocus({
    scene,
    activePageId,
    selectedNodeId,
    diagnostics: [...diagnostics, ...renderDiagnostics]
  });
  const focusedDiagnosticKeys = new Set(focusedDiagnostics.map(diagnosticKey));
  const remainingDiagnostics = diagnostics.filter((diagnostic) => !focusedDiagnosticKeys.has(diagnosticKey(diagnostic)));
  const remainingRenderDiagnostics = renderDiagnostics.filter((diagnostic) => !focusedDiagnosticKeys.has(diagnosticKey(diagnostic)));

  return (
    <section className="inspector-section">
      <div className="section-heading">
        <TriangleAlert aria-hidden size={15} />
        Diagnostics
      </div>
      {onRunPreflight ? (
        <div className="field-row">
          <button type="button" disabled={isPreflighting} onClick={onRunPreflight}>
            <FileCheck2 aria-hidden size={14} />
            {isPreflighting ? "Validating…" : "Validate"}
          </button>
        </div>
      ) : null}
      {preflightResult ? (
        <div className="preflight-summary">
          <strong>{preflightResult.status === "applied" ? "Preflight applied" : "Preflight failed"}</strong>
          <span>
            {preflightOperationCount(preflightResult)} operation{preflightOperationCount(preflightResult) === 1 ? "" : "s"} ·{" "}
            Brand {preflightResult.brand_kit.source ?? "none"}
          </span>
        </div>
      ) : null}
      {focusedDiagnostics.length > 0 ? (
        <>
          <div className="section-heading focused-diagnostic-heading">
            <TriangleAlert aria-hidden size={15} />
            Focused diagnostics
          </div>
          <p className="muted">
            Issues tied to the selected node, current page, bound slots, or placed assets.
          </p>
          <DiagnosticGroupList
            scene={scene}
            diagnostics={focusedDiagnostics}
            compact
            ariaLabel="Focused diagnostics"
            onSelectSubject={onSelectSubject}
          />
        </>
      ) : null}
      {diagnostics.length === 0 ? (
        <p className="muted">No local diagnostics.</p>
      ) : remainingDiagnostics.length === 0 ? (
        <p className="muted">No additional local diagnostics.</p>
      ) : (
        <DiagnosticGroupList
          scene={scene}
          diagnostics={remainingDiagnostics}
          ariaLabel="Additional diagnostics"
          onSelectSubject={onSelectSubject}
        />
      )}
      {remainingRenderDiagnostics.length > 0 ? (
        <>
          <div className="section-heading preview-diagnostic-heading">
            <Eye aria-hidden size={15} />
            Canvas preview notes
          </div>
          <p className="muted">
            These notes describe where the editable canvas is approximating the canonical scene. Use export preview as
            the fidelity baseline for approval.
          </p>
          <DiagnosticGroupList
            scene={scene}
            diagnostics={remainingRenderDiagnostics}
            compact
            ariaLabel="Canvas preview diagnostics"
            onSelectSubject={onSelectSubject}
          />
        </>
      ) : null}
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

function diagnosticsForFocus({
  scene,
  activePageId,
  selectedNodeId,
  diagnostics
}: {
  scene: Scene;
  activePageId: PageId | null;
  selectedNodeId: NodeId | null;
  diagnostics: Diagnostic[];
}): Diagnostic[] {
  const seen = new Set<string>();
  return diagnostics.filter((diagnostic) => {
    const key = diagnosticKey(diagnostic);
    if (seen.has(key) || !diagnostic.subject) {
      return false;
    }
    if (!diagnosticSubjectMatchesFocus(scene, diagnostic.subject, activePageId, selectedNodeId)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function diagnosticSubjectMatchesFocus(
  scene: Scene,
  subject: DiagnosticSubject,
  activePageId: PageId | null,
  selectedNodeId: NodeId | null
): boolean {
  switch (subject.kind) {
    case "document":
      return false;
    case "page":
      return subject.id === activePageId;
    case "node":
      return nodeMatchesFocus(scene, subject.id, activePageId, selectedNodeId);
    case "slot": {
      const slot = scene.slots[subject.id] ?? null;
      return Boolean(slot?.bound_nodes.some((nodeId) => nodeMatchesFocus(scene, nodeId, activePageId, selectedNodeId)));
    }
    case "asset":
      return Object.values(scene.nodes).some(
        (node) => node.source_asset_id === subject.id && nodeMatchesFocus(scene, node.id, activePageId, selectedNodeId)
      );
  }
}

function nodeMatchesFocus(scene: Scene, nodeId: NodeId, activePageId: PageId | null, selectedNodeId: NodeId | null): boolean {
  if (selectedNodeId) {
    return nodeId === selectedNodeId;
  }
  return Boolean(activePageId && pageIdForNode(scene, nodeId) === activePageId);
}

function diagnosticKey(diagnostic: Diagnostic): string {
  return `${diagnostic.severity}:${diagnostic.phase}:${diagnostic.code}:${diagnostic.message}:${diagnostic.subject ? diagnosticSubjectLabel(diagnostic.subject) : "none"}`;
}

function DiagnosticGroupList({
  scene,
  diagnostics,
  compact = false,
  ariaLabel,
  onSelectSubject
}: {
  scene: Scene;
  diagnostics: Diagnostic[];
  compact?: boolean;
  ariaLabel: string;
  onSelectSubject?: (subject: DiagnosticSubject) => void;
}) {
  const groups = groupDiagnosticsByArtboard(scene, diagnostics);
  return (
    <ul className={`diagnostic-list grouped${compact ? " compact" : ""}`} aria-label={ariaLabel}>
      {groups.map((group) => (
        <li key={group.key} className="diagnostic-group">
          <div className="diagnostic-group-heading">
            <span>{group.label}</span>
            <small>
              {group.diagnostics.length} issue{group.diagnostics.length === 1 ? "" : "s"}
            </small>
          </div>
          <ul aria-label={`${group.label} diagnostics`}>
            {group.diagnostics.map((diagnostic) => (
              <DiagnosticListItem
                key={diagnosticKey(diagnostic)}
                diagnostic={diagnostic}
                onSelectSubject={onSelectSubject}
              />
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}

function groupDiagnosticsByArtboard(scene: Scene, diagnostics: Diagnostic[]) {
  const groups = new Map<string, { key: string; label: string; diagnostics: Diagnostic[] }>();
  for (const diagnostic of diagnostics) {
    const pageId = pageIdForDiagnostic(scene, diagnostic);
    const key = pageId ?? (diagnostic.subject?.kind === "document" ? "document" : "unmapped");
    const label = pageId ? `Artboard ${scene.pages[pageId]?.name ?? pageId}` : key === "document" ? "Document" : "Unmapped";
    const group = groups.get(key) ?? {
      key,
      label,
      diagnostics: []
    };
    group.diagnostics.push(diagnostic);
    groups.set(key, group);
  }
  return [...groups.values()];
}

function pageIdForDiagnostic(scene: Scene, diagnostic: Diagnostic): PageId | null {
  const subject = diagnostic.subject;
  if (!subject) {
    return null;
  }
  switch (subject.kind) {
    case "page":
      return scene.pages[subject.id] ? subject.id : null;
    case "node":
      return pageIdForNode(scene, subject.id);
    case "slot": {
      const slot = scene.slots[subject.id] ?? null;
      const nodeId = slot?.bound_nodes.find((id) => Boolean(scene.nodes[id])) ?? null;
      return nodeId ? pageIdForNode(scene, nodeId) : null;
    }
    case "asset": {
      const node = Object.values(scene.nodes).find((candidate) => candidate.source_asset_id === subject.id);
      return node ? pageIdForNode(scene, node.id) : null;
    }
    case "document":
      return null;
  }
}

function DiagnosticListItem({
  diagnostic,
  onSelectSubject
}: {
  diagnostic: Diagnostic;
  onSelectSubject?: (subject: DiagnosticSubject) => void;
}) {
  const subjectLabel = diagnostic.subject ? diagnosticSubjectLabel(diagnostic.subject) : null;
  const canSelect = Boolean(onSelectSubject && diagnostic.subject && diagnostic.subject.kind !== "document");
  return (
    <li className={diagnostic.severity}>
      <strong>{diagnostic.code}</strong>
      <span>{diagnostic.message}</span>
      {diagnostic.subject ? (
        <button
          type="button"
          className="diagnostic-subject-button"
          disabled={!canSelect}
          onClick={() => diagnostic.subject && onSelectSubject?.(diagnostic.subject)}
        >
          {canSelect ? `Show ${subjectLabel}` : subjectLabel}
        </button>
      ) : null}
    </li>
  );
}

function diagnosticSubjectLabel(subject: DiagnosticSubject): string {
  switch (subject.kind) {
    case "document":
      return "document";
    case "page":
      return `artboard ${subject.id}`;
    case "node":
      return `node ${subject.id}`;
    case "slot":
      return `slot ${subject.id}`;
    case "asset":
      return `asset ${subject.id}`;
  }
}

function preflightOperationCount(result: EditorPreflightResult): number {
  return (
    result.preflight.brand_ref_operations +
    result.preflight.token_operations +
    result.preflight.layout_operations
  );
}
