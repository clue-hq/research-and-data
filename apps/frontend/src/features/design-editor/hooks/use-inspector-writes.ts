"use client";

import { useEffect, useRef } from "react";
import { inspectorChangeToOperation } from "../adapter/apply";
import type { LoadedWebDocument } from "../engine/webDocuments";
import type { WebArtifactSelection } from "./use-web-artifact-selection";
import {
  useWebManualEdits,
  type WebManualEdits,
} from "./use-web-manual-edits";

/**
 * W3.2: the write wiring — listens to the inspector's
 * `clue:inspector-property-change` events (the W3.1-addressed seam), maps
 * each addressable change through the pure `inspectorChangeToOperation`
 * adapter, and persists it via the ported manual-edits controller (one
 * in-flight mutation, `base_version` on every apply, 409 → quiet reload +
 * note, 422 → first diagnostic as inline error).
 *
 * The W3.1 null contract is enforced here: an event without a `selectionId`
 * or `documentVersion`, or addressed to a node other than the current
 * selection, is IGNORED — dummy-state interactions can never become writes.
 */
export function useInspectorWrites({
  document,
  documentId,
  onReload,
  selection,
}: {
  document: LoadedWebDocument | null;
  documentId: string | null;
  onReload: () => void;
  selection: WebArtifactSelection | null;
}): WebManualEdits {
  const edits = useWebManualEdits({
    baseVersion: document?.currentVersion ?? null,
    documentId: documentId ?? "",
    onReload,
  });

  // Latest-value refs so the one listener reads current state without
  // re-arming (updated passively per the repo's react-hooks rules).
  const selectionRef = useRef(selection);
  const documentRef = useRef(document);
  const applyOpsRef = useRef(edits.applyOps);
  useEffect(() => {
    applyOpsRef.current = edits.applyOps;
    documentRef.current = document;
    selectionRef.current = selection;
  });

  useEffect(() => {
    if (!documentId) return;
    const onChange = (event: Event) => {
      const detail = (event as CustomEvent).detail as {
        artifactId?: unknown;
        documentVersion?: unknown;
        property?: unknown;
        selectionId?: unknown;
        value?: unknown;
      } | null;
      if (!detail || typeof detail.property !== "string") return;
      // W3.1 null contract: not addressable → not a write.
      if (typeof detail.selectionId !== "string") return;
      if (typeof detail.documentVersion !== "number") return;
      const current = selectionRef.current;
      if (!current || current.node.id !== detail.selectionId) return;
      const loaded = documentRef.current;
      const pages = loaded?.webDoc?.pages;
      const page = pages?.find((candidate) =>
        Boolean(candidate.nodes?.[current.node.id]),
      );
      if (!page) return;
      const operation = inspectorChangeToOperation(
        {
          property: detail.property,
          selectionId: detail.selectionId,
          value: detail.value,
        },
        current.node,
        page.id,
      );
      if (!operation) return;
      applyOpsRef.current([operation], `inspector: ${detail.property}`);
    };
    window.addEventListener("clue:inspector-property-change", onChange);
    return () =>
      window.removeEventListener("clue:inspector-property-change", onChange);
  }, [documentId]);

  return edits;
}
