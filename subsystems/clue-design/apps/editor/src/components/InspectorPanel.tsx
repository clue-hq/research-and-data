"use client";

import type {
  BrandTokenCatalog,
  Diagnostic,
  DiagnosticSubject,
  Node,
  NodeId,
  Operation,
  Page,
  Scene
} from "@/engine/contracts";
import { isNodeLayoutManaged } from "@/engine/sceneQueries";
import type { StructuredEdit } from "@/engine/structuredEdits";
import { SlotInspector } from "./SlotInspector";
import { ImageInspectorSection } from "./ImageInspectorSection";
import { ArrangeSection } from "./inspector/ArrangeSection";
import { AutoLayoutSection } from "./inspector/AutoLayoutSection";
import { DesignTokensSection } from "./inspector/DesignTokensSection";
import { DocumentPageSection } from "./inspector/DocumentPageSection";
import { ObjectSection } from "./inspector/ObjectSection";
import { RawStyleSection } from "./inspector/RawStyleSection";
import { SizingSection } from "./inspector/SizingSection";
import { TextSection } from "./inspector/TextSection";
import { inspectorDiagnosticsForPage } from "./inspector/diagnostics";

interface InspectorPanelProps {
  scene: Scene;
  activePage: Page | null;
  selectedNode: Node | null;
  selectedNodeId: NodeId | null;
  /** Full multi-selection set (shift/Cmd+click) — drives Group eligibility. */
  selectedNodeIds?: NodeId[];
  brandTokens?: BrandTokenCatalog | null;
  diagnostics?: Diagnostic[];
  renderDiagnostics?: Diagnostic[];
  apiBaseUrl?: string;
  onOperation: (operation: Operation) => void;
  onOperations?: (operations: Operation[]) => void;
  /** Phase 1d: detach/re-attach run through the engine's structured-edit
   * path (the 1c invertible ops), not raw operations. */
  onStructuredEdit?: (edit: StructuredEdit) => void;
  onSelectSubject?: (subject: DiagnosticSubject) => void;
  /** Advanced per-document opt-out from handoff-absolute (Document section
   * toggle): keep agent auto-layout live by skipping both freeze seams. */
  layoutManagedEditing?: boolean;
  onSetLayoutManagedEditing?: (enabled: boolean) => void;
}

/**
 * The inspector orchestrator: decides which sections apply to the current
 * selection and wires them to the operation callbacks. Every section lives
 * in ./inspector as a field-binding component with no workflow policy.
 */
export function InspectorPanel({
  scene,
  activePage,
  selectedNode,
  selectedNodeId,
  selectedNodeIds,
  brandTokens,
  diagnostics = [],
  renderDiagnostics = [],
  apiBaseUrl,
  onOperation,
  onOperations,
  onStructuredEdit,
  onSelectSubject,
  layoutManagedEditing,
  onSetLayoutManagedEditing
}: InspectorPanelProps) {
  const emitOperations =
    onOperations ?? ((operations: Operation[]) => operations.forEach(onOperation));
  if (!selectedNode) {
    const pageDiagnostics = activePage
      ? inspectorDiagnosticsForPage(scene, activePage.id, [...diagnostics, ...renderDiagnostics])
      : [];
    return (
      <DocumentPageSection
        scene={scene}
        activePage={activePage}
        brandTokens={brandTokens}
        pageDiagnostics={pageDiagnostics}
        onOperation={onOperation}
        onSelectSubject={onSelectSubject}
        layoutManagedEditing={layoutManagedEditing}
        onSetLayoutManagedEditing={onSetLayoutManagedEditing}
      />
    );
  }

  const layoutManaged = isNodeLayoutManaged(scene, selectedNode.id);

  return (
    <>
      <ObjectSection
        scene={scene}
        activePage={activePage}
        selectedNode={selectedNode}
        selectedNodeId={selectedNodeId}
        diagnostics={diagnostics}
        renderDiagnostics={renderDiagnostics}
        onOperation={onOperation}
        onStructuredEdit={onStructuredEdit}
        onSelectSubject={onSelectSubject}
        layoutManagedEditing={layoutManagedEditing}
      />

      {onStructuredEdit ? (
        <ArrangeSection
          scene={scene}
          selectedNode={selectedNode}
          selectedNodeIds={selectedNodeIds ?? [selectedNode.id]}
          onStructuredEdit={onStructuredEdit}
          onOperations={emitOperations}
        />
      ) : null}

      {selectedNode.kind.kind === "image" ? (
        <ImageInspectorSection
          node={selectedNode}
          asset={scene.assets[selectedNode.kind.asset_id] ?? null}
          apiBaseUrl={apiBaseUrl ?? "http://localhost:8000"}
          disabled={selectedNode.locked}
          onOperations={emitOperations}
        />
      ) : null}

      <SizingSection selectedNode={selectedNode} onOperation={onOperation} />

      <RawStyleSection selectedNode={selectedNode} brandTokens={brandTokens} onOperation={onOperation} />

      {brandTokens ? (
        <DesignTokensSection
          selectedNode={selectedNode}
          brandTokens={brandTokens}
          onOperation={onOperation}
        />
      ) : null}

      {selectedNode.kind.kind === "auto_layout" || selectedNode.layout || layoutManaged ? (
        <AutoLayoutSection
          selectedNode={selectedNode}
          brandTokens={brandTokens}
          onOperation={onOperation}
        />
      ) : null}

      {selectedNode.kind.kind === "text" ? (
        <TextSection
          selectedNode={selectedNode as Parameters<typeof TextSection>[0]["selectedNode"]}
          brandTokens={brandTokens}
          onOperation={onOperation}
        />
      ) : null}

      <SlotInspector
        scene={scene}
        selectedNode={selectedNode}
        selectedNodeId={selectedNodeId}
        onOperation={onOperation}
        onOperations={onOperations}
      />
    </>
  );
}
