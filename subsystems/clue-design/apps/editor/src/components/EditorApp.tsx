"use client";

import { useMemo, useState } from "react";
import { Download, FileCheck2, PanelRightClose, RotateCcw, Send } from "lucide-react";
import { CanvasSurface } from "./canvas/CanvasSurface";
import { InspectorPanel } from "./InspectorPanel";
import { PageRail } from "./PageRail";
import { ValidationPanel } from "./ValidationPanel";
import { minimalScene } from "@/fixtures/minimalScene";
import type { Diagnostic, NodeId, Operation, PageId, Scene } from "@/engine/contracts";
import { localEditorEngine } from "@/engine/editorEngine";
import { firstPageId, getNode } from "@/engine/sceneQueries";

export interface EditorAppProps {
  initialScene?: Scene;
  initialSelectedNodeId?: NodeId | null;
}

export default function EditorApp({
  initialScene = minimalScene,
  initialSelectedNodeId = "node_contact_name"
}: EditorAppProps = {}) {
  const [scene, setScene] = useState<Scene>(initialScene);
  const [activePageId, setActivePageId] = useState<PageId | null>(() => firstPageId(initialScene));
  const [selectedNodeId, setSelectedNodeId] = useState<NodeId | null>(initialSelectedNodeId);
  const [diagnostics, setDiagnostics] = useState<Diagnostic[]>([]);
  const [lastOperation, setLastOperation] = useState<Operation | null>(null);
  const [undoStack, setUndoStack] = useState<Scene[]>([]);
  const selectedNode = useMemo(() => getNode(scene, selectedNodeId), [scene, selectedNodeId]);
  const activePage = activePageId ? scene.pages[activePageId] ?? null : null;

  const applyOperation = (operation: Operation) => {
    setLastOperation(operation);
    setScene((currentScene) => {
      const result = localEditorEngine.applyOperation(currentScene, operation);
      if (result.accepted) {
        setUndoStack((stack) => [...stack.slice(-49), currentScene]);
        setDiagnostics([]);
        return result.scene;
      }

      setDiagnostics([
        {
          severity: "error",
          phase: "operation",
          code: "EDITOR_LOCAL_APPLY",
          message: result.message ?? "Operation was rejected by the local editor engine",
          subject: selectedNodeId
            ? {
                kind: "node",
                id: selectedNodeId
              }
            : null,
          hint: "The editor will use checked core/WASM operation application once that workstream is available."
        }
      ]);
      return currentScene;
    });
  };

  const undoLastOperation = () => {
    setUndoStack((stack) => {
      const previousScene = stack[stack.length - 1];
      if (!previousScene) {
        return stack;
      }
      setScene(previousScene);
      setLastOperation(null);
      setDiagnostics([]);
      return stack.slice(0, -1);
    });
  };

  const runValidationPlaceholder = () => {
    setDiagnostics([
      {
        severity: "advice",
        phase: "validation",
        code: "EDITOR_VALIDATION_PORT",
        message: "Validation UI is wired; checked Rust validation will plug into this port later.",
        subject: null,
        hint: "This branch intentionally does not redefine core validation semantics."
      }
    ]);
  };

  const selectPage = (pageId: PageId) => {
    setActivePageId(pageId);
    setSelectedNodeId(null);
  };

  return (
    <main className="editor-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">ABM Design Engine</p>
          <h1>{scene.meta.title}</h1>
        </div>
        <div className="toolbar" aria-label="Editor actions">
          <button type="button" onClick={runValidationPlaceholder}>
            <FileCheck2 aria-hidden size={16} />
            Validate
          </button>
          <button type="button" disabled>
            <Send aria-hidden size={16} />
            Agent
          </button>
          <button type="button" disabled>
            <Download aria-hidden size={16} />
            Export
          </button>
          <button type="button" onClick={undoLastOperation} disabled={undoStack.length === 0}>
            <RotateCcw aria-hidden size={16} />
            Undo
          </button>
        </div>
      </header>
      <div className="workspace-grid">
        <PageRail scene={scene} activePageId={activePageId} onSelectPage={selectPage} />
        <CanvasSurface
          scene={scene}
          activePageId={activePageId}
          selectedNodeId={selectedNodeId}
          onSelectNode={setSelectedNodeId}
          onOperation={applyOperation}
        />
        <aside className="inspector-shell">
          <div className="panel-title">
            <PanelRightClose aria-hidden size={16} />
            Inspector
          </div>
          <InspectorPanel
            scene={scene}
            activePage={activePage}
            selectedNode={selectedNode}
            selectedNodeId={selectedNodeId}
            onOperation={applyOperation}
          />
          <ValidationPanel diagnostics={diagnostics} lastOperation={lastOperation} />
        </aside>
      </div>
    </main>
  );
}
