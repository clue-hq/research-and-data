import type { BrandKitSummary, Operation, Scene } from "./contracts";
import type { BrandKitDetailPayload } from "./tokenColors";

/**
 * Phase 2a: document identity for the editor.
 *
 * Every canvas becomes a document (Moda's model): the editor auto-creates one
 * at the first persisting action and loads one from `?document=<id>`. These
 * are the two thin API calls that back that — creation lets the SERVER mint
 * the document id (the local scene carries only the `doc_untitled`
 * placeholder), and loading returns the authoritative scene for
 * `EditorApp initialScene`.
 *
 * Workspace auth is the BFF's job — the browser never stamps headers. Every
 * fetcher therefore defaults `fetchImpl = fetch`; production callers inject
 * the BFF transport (`designBffConfig()`), which carries the session.
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
  /** Advanced per-document opt-out from handoff-absolute: when true the
   * editor skips both freeze seams so agent auto-layout stays live. */
  layoutManagedEditing: boolean;
}

export async function createDocument(
  // Workspace auth is the BFF's job — the browser never stamps headers.
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
  // Workspace auth is the BFF's job — the browser never stamps headers.
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
  // Workspace auth is the BFF's job — the browser never stamps headers.
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
    layout_managed_editing?: unknown;
  };
  if (!payload.scene || typeof payload.scene !== "object") {
    throw new Error("document fetch returned no scene");
  }
  return {
    documentId: typeof payload.id === "string" ? payload.id : documentId,
    title: typeof payload.title === "string" ? payload.title : "Untitled design",
    scene: payload.scene as Scene,
    agentInstructions:
      typeof payload.agent_instructions === "string" ? payload.agent_instructions : null,
    layoutManagedEditing: payload.layout_managed_editing === true
  };
}

/**
 * The stored Brand Kit summaries (latest version per kit) that the Brand Kit
 * dropdown can offer for attachment. Callers should treat a fetch failure as
 * "no kits available yet" rather than block the editor from loading — this
 * list only gates the dropdown, not the canvas.
 */
export async function fetchBrandKits(
  // Workspace auth is the BFF's job — the browser never stamps headers.
  { apiBaseUrl, fetchImpl = fetch }: DocumentStoreOptions
): Promise<BrandKitSummary[]> {
  const response = await fetchImpl(new URL("/brand-kits", apiBaseUrl));
  if (!response.ok) {
    throw new Error(`brand kit list failed (HTTP ${response.status})`);
  }
  const payload = (await response.json()) as unknown;
  return Array.isArray(payload) ? (payload as BrandKitSummary[]) : [];
}

/**
 * The full raw brand-kit JSON for one stored kit (`GET
 * /brand-kits/{id}` -> `brand_kit_json`) — the resolved token *values*, not
 * just the name/count summary `fetchBrandKits` returns. Used to build the
 * canvas token-color map (see `tokenColors.ts`); callers should treat a
 * fetch failure the same way `fetchBrandKits` does (leave the canvas on the
 * string-heuristic fallback) rather than block anything on it.
 */
export async function fetchBrandKitDetail(
  // Workspace auth is the BFF's job — the browser never stamps headers.
  { apiBaseUrl, fetchImpl = fetch }: DocumentStoreOptions,
  brandKitId: string
): Promise<BrandKitDetailPayload | null> {
  const response = await fetchImpl(
    new URL(`/brand-kits/${encodeURIComponent(brandKitId)}`, apiBaseUrl)
  );
  if (!response.ok) {
    throw new Error(`brand kit detail fetch failed (HTTP ${response.status})`);
  }
  const payload = (await response.json()) as { brand_kit_json?: unknown };
  return (payload.brand_kit_json as BrandKitDetailPayload | undefined) ?? null;
}

/** K1.6(b): the server-resolved + server-frozen accept bake. The scene comes
 * back with tokens resolved to literals, layout re-solved with real
 * (SkParagraph) measurement, and every Stack container baked to Free — the
 * raw operations let the accept envelope commit resolution + freeze in the
 * same batch as the turn's ops. Null when the server declined to bake (a
 * preflight error); callers fall back to the client-side freeze. */
export interface AcceptBakeResult {
  scene: Scene;
  resolutionOperations: Operation[];
  freezeOperations: Operation[];
  freezeInverseOperations: Operation[];
}

export async function resolveAndFreezeScene(
  // Workspace auth is the BFF's job — the browser never stamps headers.
  { apiBaseUrl, fetchImpl = fetch }: DocumentStoreOptions,
  scene: Scene
): Promise<AcceptBakeResult | null> {
  const response = await fetchImpl(new URL("/preflight-preview", apiBaseUrl), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ scene, freeze_layout: true })
  });
  if (!response.ok) {
    throw new Error(`accept bake failed (HTTP ${response.status})`);
  }
  const payload = (await response.json()) as {
    bake?: {
      scene?: Scene;
      resolution_operations?: Operation[];
      freeze_operations?: Operation[];
      freeze_inverse_operations?: Operation[];
    };
  };
  const bake = payload.bake;
  if (!bake?.scene) {
    return null;
  }
  return {
    scene: bake.scene,
    resolutionOperations: bake.resolution_operations ?? [],
    freezeOperations: bake.freeze_operations ?? [],
    freezeInverseOperations: bake.freeze_inverse_operations ?? []
  };
}

/** 2e: persist the document's standing agent instructions (blank clears). */
export async function saveAgentInstructions(
  // Workspace auth is the BFF's job — the browser never stamps headers.
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

/** Persist the document's layout-managed-editing opt-out (see
 * LoadedDocument.layoutManagedEditing). Returns the persisted value. */
export async function saveLayoutManagedEditing(
  // Workspace auth is the BFF's job — the browser never stamps headers.
  { apiBaseUrl, fetchImpl = fetch }: DocumentStoreOptions,
  documentId: string,
  enabled: boolean
): Promise<boolean> {
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}/layout-managed-editing`, apiBaseUrl),
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ enabled })
    }
  );
  if (!response.ok) {
    throw new Error(`saving layout-managed editing failed (HTTP ${response.status})`);
  }
  const payload = (await response.json()) as { layout_managed_editing?: unknown };
  return payload.layout_managed_editing === true;
}
