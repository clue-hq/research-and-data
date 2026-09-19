import { z } from "zod";
import { defaultDesignFetch } from "../engine/config";

/**
 * `GET /documents/{id}/agent-run` — the document-scoped agent-busy read (scene
 * live-streaming rung A follow-up). Answers from the same predicate the design
 * API's manual-write 409 uses, so a page that locks on it can never disagree
 * with the server about whether a run is driving the document.
 */
const documentAgentRunWire = z.object({
  schema_version: z.literal(1),
  document_id: z.string().min(1),
  active: z.boolean(),
  run_id: z.string().min(1).nullable(),
  current_version: z.number().int().nonnegative(),
});

export interface DocumentAgentRun {
  active: boolean;
  runId: string | null;
  currentVersion: number;
}

export async function fetchDocumentAgentRun(
  // Workspace auth is the BFF's job — callers inject designBffConfig()'s transport.
  { apiBaseUrl, fetchImpl = defaultDesignFetch }: { apiBaseUrl: string; fetchImpl?: typeof fetch },
  documentId: string,
): Promise<DocumentAgentRun> {
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}/agent-run`, apiBaseUrl),
  );
  if (!response.ok) {
    throw new Error(`agent-run read failed for ${documentId} (HTTP ${response.status})`);
  }
  const wire = documentAgentRunWire.parse(await response.json());
  return { active: wire.active, runId: wire.run_id, currentVersion: wire.current_version };
}
