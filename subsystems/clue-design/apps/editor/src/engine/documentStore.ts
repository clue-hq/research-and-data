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
  };
  if (!payload.scene || typeof payload.scene !== "object") {
    throw new Error("document fetch returned no scene");
  }
  return {
    documentId: typeof payload.id === "string" ? payload.id : documentId,
    title: typeof payload.title === "string" ? payload.title : "Untitled design",
    scene: payload.scene as Scene
  };
}
