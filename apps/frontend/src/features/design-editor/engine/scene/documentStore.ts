import { parseRenderContext, type RenderContext } from "./renderContext";
// PLATFORM DELTA (AD3.3) — this module is otherwise verbatim upstream code. The
// one divergence is that `LoadedDocument`/`fetchDocument` now also parse the
// three history fields `GET /documents/{id}` already returns —
// `current_version`, `undo_stack`, `redo_stack` — as `currentVersion` /
// `undoDepth` / `redoDepth`. It is not a new idea: the SIBLING extracted loader
// in this repo, `engine/webDocuments.ts:366-369` (`fetchWebDocument`), performs
// exactly this parse for web documents, down to the
// `Array.isArray(payload.undo_stack) ? payload.undo_stack.length : 0` form —
// this makes the scene loader its equal instead of leaving the ad lane unable
// to say whether an undo step exists. An upstream re-sync must re-apply the
// delta, not straight-copy.
import { defaultDesignFetch } from "../config";
import type { BrandKitSummary, Operation, Scene } from "./contracts";
import type { BrandKitDetailPayload } from "./tokenColors";
import { PLATFORM_DEFAULT_BRAND_KIT_ID } from "./tokenColors";

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
 * fetcher therefore defaults `fetchImpl = defaultDesignFetch` (the config
 * seam's receiver-safe wrapper); production callers inject the BFF transport
 * (`designBffConfig()`), which carries the session.
 */

export interface DocumentStoreOptions {
  apiBaseUrl: string;
  fetchImpl?: typeof fetch;
}

export interface CreatedDocument {
  documentId: string;
}

export interface LoadedDocument {
  renderContext: RenderContext | null;
  documentId: string;
  title: string;
  scene: Scene;
  /** 2e: the document's standing agent instructions (null when unset). */
  agentInstructions: string | null;
  /** Advanced per-document opt-out from handoff-absolute: when true the
   * editor skips both freeze seams so agent auto-layout stays live. */
  layoutManagedEditing: boolean;
  /** PLATFORM DELTA (AD3.3, see the file header): the document's committed
   * version, and the true depths of its server-side undo/redo stacks at the
   * moment of this load. Mirrors `LoadedWebDocument`
   * (`engine/webDocuments.ts:366-369`). */
  currentVersion: number | null;
  undoDepth: number;
  redoDepth: number;
}

export async function createDocument(
  // Workspace auth is the BFF's job — defaults to the receiver-safe wrapper; callers inject designBffConfig()'s transport.
  { apiBaseUrl, fetchImpl = defaultDesignFetch }: DocumentStoreOptions,
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
  // Workspace auth is the BFF's job — defaults to the receiver-safe wrapper; callers inject designBffConfig()'s transport.
  const { apiBaseUrl, fetchImpl = defaultDesignFetch } = options;
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

/** PLATFORM DELTA (Lane C, master plan Review focus 1): a site document is a Puck
 * site, not a scene. Before Lane A's A1 mapper lands the wire can still call it
 * `ad`; the scene editor must refuse it rather than draw it. */
export const SITE_DOCUMENT_IN_SCENE_EDITOR =
  "This website opens in the website editor, not the ad canvas.";

export async function fetchDocument(
  // Workspace auth is the BFF's job — defaults to the receiver-safe wrapper; callers inject designBffConfig()'s transport.
  { apiBaseUrl, fetchImpl = defaultDesignFetch }: DocumentStoreOptions,
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
    render_context?: unknown;
    agent_instructions?: unknown;
    layout_managed_editing?: unknown;
    current_version?: unknown;
    undo_stack?: unknown;
    redo_stack?: unknown;
    doc_kind?: unknown;
  };
  if (payload.doc_kind === "site") {
    throw new Error(SITE_DOCUMENT_IN_SCENE_EDITOR);
  }
  if (!payload.scene || typeof payload.scene !== "object") {
    throw new Error("document fetch returned no scene");
  }
  return {
    documentId: typeof payload.id === "string" ? payload.id : documentId,
    title: typeof payload.title === "string" ? payload.title : "Untitled design",
    scene: payload.scene as Scene,
    renderContext: parseRenderContext(payload.render_context,
      typeof payload.id === "string" ? payload.id : documentId,
      "current_version" in payload && typeof payload.current_version === "number" ? payload.current_version : null),
    agentInstructions:
      typeof payload.agent_instructions === "string" ? payload.agent_instructions : null,
    layoutManagedEditing: payload.layout_managed_editing === true,
    // PLATFORM DELTA (AD3.3) — the same three lines as
    // `engine/webDocuments.ts:366-369`, against the same endpoint. A payload
    // without the stacks (an older server) reads as depth 0, which disables the
    // history controls rather than offering a step that would fail.
    currentVersion:
      typeof payload.current_version === "number" ? payload.current_version : null,
    undoDepth: Array.isArray(payload.undo_stack) ? payload.undo_stack.length : 0,
    redoDepth: Array.isArray(payload.redo_stack) ? payload.redo_stack.length : 0
  };
}

/**
 * The stored Brand Kit summaries (latest version per kit) that the Brand Kit
 * dropdown can offer for attachment. Callers should treat a fetch failure as
 * "no kits available yet" rather than block the editor from loading — this
 * list only gates the dropdown, not the canvas.
 */
export async function fetchBrandKits(
  // Workspace auth is the BFF's job — defaults to the receiver-safe wrapper; callers inject designBffConfig()'s transport.
  { apiBaseUrl, fetchImpl = defaultDesignFetch }: DocumentStoreOptions
): Promise<BrandKitSummary[]> {
  const response = await fetchImpl(new URL("/brand-kits", apiBaseUrl));
  if (!response.ok) {
    throw new Error(`brand kit list failed (HTTP ${response.status})`);
  }
  const payload = (await response.json()) as unknown;
  return Array.isArray(payload) ? (payload as BrandKitSummary[]) : [];
}

/**
 * The full raw brand-kit JSON for one stored kit — the resolved token
 * *values*, not just the name/count summary `fetchBrandKits` returns.
 *
 * A document-bound caller MUST pass the scene's pinned version. Stored kits
 * then resolve through `/brand-kits/{id}/versions/{version}` so a document
 * authored against v6 cannot silently render with today's v9. The engine-builtin
 * platform fallback kit is the one exception: it has no registry row, so the
 * versioned route 404s for it, and only `/brand-kits/{id}` synthesizes it — yet
 * preflight stamps its fixture version (1) into kit-less scenes, so the builtin
 * id must always take the versionless route regardless of the pinned version.
 */
export async function fetchBrandKitDetail(
  // Workspace auth is the BFF's job — defaults to the receiver-safe wrapper; callers inject designBffConfig()'s transport.
  { apiBaseUrl, fetchImpl = defaultDesignFetch }: DocumentStoreOptions,
  brandKitId: string,
  brandKitVersion: number | null = null
): Promise<BrandKitDetailPayload | null> {
  if (brandKitId === PLATFORM_DEFAULT_BRAND_KIT_ID) {
    brandKitVersion = null;
  }
  const encodedId = encodeURIComponent(brandKitId);
  const path =
    brandKitVersion !== null && brandKitVersion > 0
      ? `/brand-kits/${encodedId}/versions/${brandKitVersion}`
      : `/brand-kits/${encodedId}`;
  const response = await fetchImpl(
    new URL(path, apiBaseUrl)
  );
  if (!response.ok) {
    const ref =
      brandKitVersion !== null && brandKitVersion > 0
        ? `${brandKitId}@${brandKitVersion}`
        : brandKitId;
    throw new Error(
      `brand kit detail fetch failed for ${ref} (HTTP ${response.status})`
    );
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
  // Workspace auth is the BFF's job — defaults to the receiver-safe wrapper; callers inject designBffConfig()'s transport.
  { apiBaseUrl, fetchImpl = defaultDesignFetch }: DocumentStoreOptions,
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
  // Workspace auth is the BFF's job — defaults to the receiver-safe wrapper; callers inject designBffConfig()'s transport.
  { apiBaseUrl, fetchImpl = defaultDesignFetch }: DocumentStoreOptions,
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
  // Workspace auth is the BFF's job — defaults to the receiver-safe wrapper; callers inject designBffConfig()'s transport.
  { apiBaseUrl, fetchImpl = defaultDesignFetch }: DocumentStoreOptions,
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

/** A refused rename: the HTTP status and the design API's refusal code
 * (`detail.code`, null when it sent none), so a caller can tell refusals apart
 * without parsing prose — e.g. 409 `document.agent_run_active` while a design
 * run drives the document (K1-5, founder ruling 2026-10-16). */
export class DocumentRenameError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(message: string, options: { status: number; code: string | null }) {
    super(message);
    this.name = "DocumentRenameError";
    this.status = options.status;
    this.code = options.code;
  }
}

/** Artifacts page (2026-09-15): persist a new title (row + document JSON; the version advances).
 * A refusal throws a {@link DocumentRenameError}. */
export async function renameDocument(
  // Workspace auth is the BFF's job — defaults to the receiver-safe wrapper; callers inject designBffConfig()'s transport.
  { apiBaseUrl, fetchImpl = defaultDesignFetch }: DocumentStoreOptions,
  documentId: string,
  title: string
): Promise<string> {
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}/title`, apiBaseUrl),
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title })
    }
  );
  if (!response.ok) {
    let code: string | null = null;
    try {
      const detail = ((await response.json()) as { detail?: { code?: unknown } } | null)?.detail;
      code = typeof detail?.code === "string" ? detail.code : null;
    } catch {
      /* not JSON — no refusal code */
    }
    throw new DocumentRenameError(`renaming the document failed (HTTP ${response.status})`, {
      status: response.status,
      code,
    });
  }
  const payload = (await response.json()) as { title?: unknown };
  if (typeof payload.title !== "string") {
    throw new Error("renaming the document returned no title");
  }
  return payload.title;
}

/** Artifacts page (2026-09-15): archive or restore. Returns the archive timestamp, null when live. */
export async function saveDocumentArchived(
  // Workspace auth is the BFF's job — defaults to the receiver-safe wrapper; callers inject designBffConfig()'s transport.
  { apiBaseUrl, fetchImpl = defaultDesignFetch }: DocumentStoreOptions,
  documentId: string,
  archived: boolean
): Promise<string | null> {
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}/archived`, apiBaseUrl),
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ archived })
    }
  );
  if (!response.ok) {
    throw new Error(`archiving the document failed (HTTP ${response.status})`);
  }
  const payload = (await response.json()) as { archived_at?: unknown };
  return typeof payload.archived_at === "string" ? payload.archived_at : null;
}
