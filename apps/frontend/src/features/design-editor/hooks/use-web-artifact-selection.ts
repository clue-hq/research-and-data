"use client";

import { useCallback, useEffect, useState } from "react";
import {
  hydrateInspectorState,
  inspectorSelectionFor,
  type InspectorSchemaSelection,
} from "../adapter/hydrate";
import type { InspectorPresentationState } from "@/features/chat-shell/hooks/use-inspector-controller";
import type { WebSelection } from "../engine/webBridge";
import {
  fetchWebDocument,
  type LoadedWebDocument,
  type WebNode,
} from "../engine/webDocuments";
import { designBffConfig } from "../data/design-bff";

/**
 * W2.2: the selection state the plan names — `{node: WebNode, nodeInfo:
 * WebSelection}` — realized by joining the canvas bridge's selection events
 * (nonce-validated by the ported listener inside WebArtifactCanvas) with the
 * loaded web document's node map, plus the derived schema + hydrated
 * inspector state from the pure adapter.
 *
 * The document load also carries `currentVersion` — W3's write path takes its
 * `base_version` from here, so the join owner is deliberately this hook, not
 * the canvas (which stays a pure render surface).
 *
 * Loaded/selected values are stamped with the document id they were captured
 * for and DERIVED against the current id (never reset synchronously in an
 * effect — react-hooks/set-state-in-effect); a stale document's leftovers are
 * simply never served.
 */
export interface WebArtifactSelection {
  node: WebNode;
  nodeInfo: WebSelection;
  schema: InspectorSchemaSelection;
  hydrated: Partial<InspectorPresentationState>;
}

interface StampedDocument {
  forDocumentId: string;
  document: LoadedWebDocument;
}

interface StampedSelection {
  forDocumentId: string;
  nodeInfo: WebSelection | null;
}

function joinSelection(
  document: LoadedWebDocument | null,
  nodeInfo: WebSelection | null,
): WebArtifactSelection | null {
  if (!nodeInfo || !document) return null;
  const webDoc = document.webDoc;
  if (!webDoc || !Array.isArray(webDoc.pages)) return null;
  for (const page of webDoc.pages) {
    const node = page.nodes?.[nodeInfo.nodeId];
    if (node) {
      return {
        node,
        nodeInfo,
        schema: inspectorSelectionFor(node, page.root ?? ""),
        hydrated: hydrateInspectorState(node, node.classes ?? ""),
      };
    }
  }
  return null;
}

export function useWebArtifactSelection(
  documentId: string | null,
  /** W3.2: bump to quietly refetch the document after a committed write
   * (the manual-edits controller's `onReload`). */
  reloadToken = 0,
): {
  /** Feed to WebArtifactCanvas's `onSelect`. */
  onSelect: (selection: WebSelection | null) => void;
  /** The joined selection, or null (nothing selected / doc not loaded /
   * the selected id is not in the document). */
  selection: WebArtifactSelection | null;
  /** The loaded document (null while loading or on failure). */
  document: LoadedWebDocument | null;
} {
  const [loaded, setLoaded] = useState<StampedDocument | null>(null);
  const [selected, setSelected] = useState<StampedSelection | null>(null);

  useEffect(() => {
    if (!documentId) return;
    let cancelled = false;
    fetchWebDocument(designBffConfig(), documentId)
      .then((document) => {
        if (!cancelled) setLoaded({ document, forDocumentId: documentId });
      })
      .catch(() => {
        // A failed document load only disables selection join/hydration; the
        // canvas render (and its own error surface) is independent.
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, reloadToken]);

  const onSelect = useCallback(
    (selection: WebSelection | null) => {
      if (!documentId) return;
      setSelected({ forDocumentId: documentId, nodeInfo: selection });
    },
    [documentId],
  );

  const document =
    documentId && loaded?.forDocumentId === documentId ? loaded.document : null;
  const nodeInfo =
    documentId && selected?.forDocumentId === documentId
      ? selected.nodeInfo
      : null;

  return { document, onSelect, selection: joinSelection(document, nodeInfo) };
}
