"use client";

import type { Diagnostic, DiagnosticSubject, Node, NodeId, Page, Scene } from "@/engine/contracts";
import { flattenPageNodeIds } from "@/engine/sceneQueries";

/** Inspector-scoped diagnostics: scope filtering, dedupe, and the compact
 * issue list section. */

export function InspectorDiagnosticsSection({
  title,
  diagnostics,
  onSelectSubject
}: {
  title: string;
  diagnostics: Diagnostic[];
  onSelectSubject?: (subject: DiagnosticSubject) => void;
}) {
  if (diagnostics.length === 0) {
    return null;
  }
  return (
    <div className="inspector-diagnostics" aria-label={title}>
      <div className="section-heading nested-heading">{title}</div>
      <ul className="diagnostic-list compact">
        {diagnostics.map((diagnostic) => (
          <InspectorDiagnosticItem
            key={diagnosticKey(diagnostic)}
            diagnostic={diagnostic}
            onSelectSubject={onSelectSubject}
          />
        ))}
      </ul>
    </div>
  );
}

function InspectorDiagnosticItem({
  diagnostic,
  onSelectSubject
}: {
  diagnostic: Diagnostic;
  onSelectSubject?: (subject: DiagnosticSubject) => void;
}) {
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
          {canSelect ? `Show ${diagnosticSubjectLabel(diagnostic.subject)}` : diagnosticSubjectLabel(diagnostic.subject)}
        </button>
      ) : null}
    </li>
  );
}

export function inspectorDiagnosticsForNode(scene: Scene, node: Node, diagnostics: Diagnostic[]): Diagnostic[] {
  const scopedNodeIds = nodeScopeIds(scene, node.id);
  return dedupeDiagnostics(
    diagnostics.filter((diagnostic) => diagnostic.subject && diagnosticSubjectMatchesNodeScope(scene, diagnostic.subject, scopedNodeIds))
  );
}

export function inspectorDiagnosticsForPage(scene: Scene, pageId: Page["id"], diagnostics: Diagnostic[]): Diagnostic[] {
  const pageNodeIds = new Set(flattenPageNodeIds(scene, pageId));
  return dedupeDiagnostics(
    diagnostics.filter((diagnostic) => diagnostic.subject && diagnosticSubjectMatchesPageScope(scene, diagnostic.subject, pageId, pageNodeIds))
  );
}

function diagnosticSubjectMatchesNodeScope(
  scene: Scene,
  subject: DiagnosticSubject,
  scopedNodeIds: Set<NodeId>
): boolean {
  switch (subject.kind) {
    case "document":
    case "page":
      return false;
    case "node":
      return scopedNodeIds.has(subject.id);
    case "slot": {
      const slot = scene.slots[subject.id] ?? null;
      return Boolean(slot?.bound_nodes.some((nodeId) => scopedNodeIds.has(nodeId)));
    }
    case "asset":
      return [...scopedNodeIds].some((nodeId) => nodeUsesAsset(scene.nodes[nodeId], subject.id));
  }
}

function diagnosticSubjectMatchesPageScope(
  scene: Scene,
  subject: DiagnosticSubject,
  pageId: Page["id"],
  pageNodeIds: Set<NodeId>
): boolean {
  switch (subject.kind) {
    case "document":
      return false;
    case "page":
      return subject.id === pageId;
    case "node":
      return pageNodeIds.has(subject.id);
    case "slot": {
      const slot = scene.slots[subject.id] ?? null;
      return Boolean(slot?.bound_nodes.some((nodeId) => pageNodeIds.has(nodeId)));
    }
    case "asset":
      return [...pageNodeIds].some((nodeId) => nodeUsesAsset(scene.nodes[nodeId], subject.id));
  }
}

function nodeScopeIds(scene: Scene, nodeId: NodeId): Set<NodeId> {
  const ids = new Set<NodeId>();
  const visit = (currentId: NodeId) => {
    if (ids.has(currentId)) {
      return;
    }
    const node = scene.nodes[currentId];
    if (!node) {
      return;
    }
    ids.add(currentId);
    for (const childId of node.children) {
      visit(childId);
    }
  };
  visit(nodeId);
  return ids;
}

function nodeUsesAsset(node: Node | undefined, assetId: string): boolean {
  return Boolean(node && (node.source_asset_id === assetId || (node.kind.kind === "image" && node.kind.asset_id === assetId)));
}

function dedupeDiagnostics(diagnostics: Diagnostic[]): Diagnostic[] {
  const seen = new Set<string>();
  return diagnostics.filter((diagnostic) => {
    const key = diagnosticKey(diagnostic);
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function diagnosticKey(diagnostic: Diagnostic): string {
  return `${diagnostic.severity}:${diagnostic.phase}:${diagnostic.code}:${diagnostic.message}:${diagnostic.subject ? diagnosticSubjectLabel(diagnostic.subject) : "none"}`;
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

export function countDiagnostics(diagnostics: Diagnostic[]): { errors: number; warnings: number } {
  let errors = 0;
  let warnings = 0;
  for (const diagnostic of diagnostics) {
    if (diagnostic.severity === "error") {
      errors += 1;
    } else if (diagnostic.severity === "warning") {
      warnings += 1;
    }
  }
  return { errors, warnings };
}

export function diagnosticCountLabel(counts: { errors: number; warnings: number }): string {
  if (counts.errors === 0 && counts.warnings === 0) {
    return "None";
  }
  const parts: string[] = [];
  if (counts.errors > 0) {
    parts.push(`${counts.errors} error${counts.errors === 1 ? "" : "s"}`);
  }
  if (counts.warnings > 0) {
    parts.push(`${counts.warnings} warning${counts.warnings === 1 ? "" : "s"}`);
  }
  return parts.join(" / ");
}
