import type { Scene } from "./contracts";

/**
 * Phase 2a: document identity for the editor.
 *
 * Every canvas becomes a document (Moda's model): the editor auto-creates one
 * at the first persisting action and loads one from `?document=<id>`. These
 * are the two thin API calls that back that — creation lets the SERVER mint
 * the document id (the local scene carries only the `doc_untitled`
 * placeholder), and loading returns the authoritative scene for
 * `EditorApp initialScene`.
 */

export interface DocumentStoreOptions {
  apiBaseUrl: string;
  fetchImpl?: typeof fetch;
}

export interface CreatedDocument {
  documentId: string;
}

export interface LoadedDocument {
  documentId: string;
  title: string;
  scene: Scene;
  /** 2e: the document's standing agent instructions (null when unset). */
  agentInstructions: string | null;
}

export async function createDocument(
  { apiBaseUrl, fetchImpl = fetch }: DocumentStoreOptions,
  scene: Scene
): Promise<CreatedDocument> {
  // Strip the local placeholder id so the server mints the real document id
  // (POST /documents adopts scene.meta.id verbatim when present, and the
  // placeholder is shared by every unsaved canvas — it would collide).
  const meta: Record<string, unknown> = { ...(scene.meta as unknown as Record<string, unknown>) };
  delete meta.id;
  const response = await fetchImpl(new URL("/documents", apiBaseUrl), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ scene: { ...scene, meta } })
  });
  if (!response.ok) {
    throw new Error(`document create failed (HTTP ${response.status})`);
  }
  const payload = (await response.json()) as { document?: { id?: unknown } };
  const documentId = payload.document?.id;
  if (typeof documentId !== "string" || documentId.length === 0) {
    throw new Error("document create returned no document id");
  }
  return { documentId };
}

/** A checkpoint revert either applies, or the server refuses it honestly:
 * the anchor may be unknown (404) or off the active undo path — already
 * reverted (409). Refusals are outcomes, not exceptions; only transport or
 * server failures throw. */
export type RevertOutcome =
  | {
      status: "applied";
      revertedBatchIds: string[];
      currentVersion: number | null;
      scene: Scene;
    }
  | { status: "refused"; code: string; message: string };

export async function revertDocument(
  options: DocumentStoreOptions,
  documentId: string,
  checkpoint: string
): Promise<RevertOutcome> {
  const { apiBaseUrl, fetchImpl = fetch } = options;
  const url = new URL(`/documents/${encodeURIComponent(documentId)}/revert`, apiBaseUrl);
  url.searchParams.set("checkpoint", checkpoint);
  const response = await fetchImpl(url, { method: "POST" });
  if (response.status === 404 || response.status === 409) {
    const payload = (await response.json().catch(() => ({}))) as {
      detail?: { code?: unknown; message?: unknown };
    };
    return {
      status: "refused",
      code: typeof payload.detail?.code === "string" ? payload.detail.code : "history.refused",
      message:
        typeof payload.detail?.message === "string"
          ? payload.detail.message
          : `The server refused reverting to ${checkpoint}.`
    };
  }
  if (!response.ok) {
    throw new Error(`revert failed (HTTP ${response.status})`);
  }
  const payload = (await response.json()) as {
    reverted_batch_ids?: unknown;
    document?: { current_version?: unknown };
  };
  // The revert response carries the document summary (no scene); fetch the
  // authoritative reverted scene through the same loader the editor uses.
  const document = await fetchDocument(options, documentId);
  return {
    status: "applied",
    revertedBatchIds: Array.isArray(payload.reverted_batch_ids)
      ? payload.reverted_batch_ids.filter((id): id is string => typeof id === "string")
      : [],
    currentVersion:
      typeof payload.document?.current_version === "number"
        ? payload.document.current_version
        : null,
    scene: document.scene
  };
}

export async function fetchDocument(
  { apiBaseUrl, fetchImpl = fetch }: DocumentStoreOptions,
  documentId: string
): Promise<LoadedDocument> {
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}`, apiBaseUrl)
  );
  if (!response.ok) {
    throw new Error(
      response.status === 404
        ? `document ${documentId} was not found`
        : `document fetch failed (HTTP ${response.status})`
    );
  }
  const payload = (await response.json()) as {
    id?: unknown;
    title?: unknown;
    scene?: unknown;
    agent_instructions?: unknown;
  };
  if (!payload.scene || typeof payload.scene !== "object") {
    throw new Error("document fetch returned no scene");
  }
  return {
    documentId: typeof payload.id === "string" ? payload.id : documentId,
    title: typeof payload.title === "string" ? payload.title : "Untitled design",
    scene: payload.scene as Scene,
    agentInstructions:
      typeof payload.agent_instructions === "string" ? payload.agent_instructions : null
  };
}

/** 2e: persist the document's standing agent instructions (blank clears). */
export async function saveAgentInstructions(
  { apiBaseUrl, fetchImpl = fetch }: DocumentStoreOptions,
  documentId: string,
  instructions: string | null
): Promise<string | null> {
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}/agent-instructions`, apiBaseUrl),
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ instructions })
    }
  );
  if (!response.ok) {
    throw new Error(`saving agent instructions failed (HTTP ${response.status})`);
  }
  const payload = (await response.json()) as { agent_instructions?: unknown };
  return typeof payload.agent_instructions === "string" ? payload.agent_instructions : null;
}
