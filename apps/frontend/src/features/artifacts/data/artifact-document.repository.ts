"use client";

import type { ImageExportFormat, ImageExportScale } from "@/features/chat-shell/model/image-export";
import {
  exportFilename,
  sceneExportProfile,
  sceneExportResultMessage,
  sceneExportScaleMultiplier,
} from "@/features/design-editor/adapter/scene-export";
import { designBffConfig } from "@/features/design-editor/data/design-bff";
import {
  renameDocument,
  saveDocumentArchived,
} from "@/features/design-editor/engine/scene/documentStore";
import { exportResultFromUnknown } from "@/features/design-editor/engine/scene/exportRunner";
import { downloadDataUrl } from "@/features/design-editor/hooks/use-scene-export";

/**
 * Artifacts page (2026-09-15): the browser-only document writes and the ad
 * export, reached the same way the editor reaches them — through the
 * same-origin BFF (`designBffConfig()`), which carries the session cookie and
 * lets the proxy stamp the workspace header server-side. Nothing here throws a
 * message it swallows: every failure leaves as an Error for the calling hook.
 */

export function renameArtifactDocument(documentId: string, title: string): Promise<string> {
  return renameDocument(designBffConfig(), documentId, title);
}

export function setArtifactArchived(documentId: string, archived: boolean): Promise<string | null> {
  return saveDocumentArchived(designBffConfig(), documentId, archived);
}

/** The saved document's export request: the same profile the ad editor sends, no scene upload
 * (the API exports the stored scene), all pages, and never a persisted preflight — the default
 * would write the token-baked preflight scene back and bump the document's version. */
export function adExportRequestBody(format: ImageExportFormat, scale: ImageExportScale) {
  const profile = sceneExportProfile(format, sceneExportScaleMultiplier(scale));
  return { format: profile.format, page_ids: [] as string[], profile, persist_preflight: false };
}

// `downloadDataUrl` is the scene export's own helper (imported above), never re-implemented here.

export async function exportAdArtifact({
  documentId,
  title,
  format,
  scale,
}: {
  documentId: string;
  title: string;
  format: ImageExportFormat;
  scale: ImageExportScale;
}): Promise<void> {
  const { apiBaseUrl, fetchImpl } = designBffConfig();
  const response = await fetchImpl!(
    new URL(`/documents/${encodeURIComponent(documentId)}/export`, apiBaseUrl),
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(adExportRequestBody(format, scale)),
    },
  );
  if (!response.ok) throw new Error(`Export request failed with HTTP ${response.status}`);
  const result = exportResultFromUnknown(await response.json());
  if (result.status !== "ok") throw new Error(sceneExportResultMessage(format, result));
  const dataUrl = result.artifacts[0]?.data_url ?? null;
  if (!dataUrl) throw new Error(`${format} export returned no file`);
  // `downloadDataUrl` reports whether a file actually left (its one deliberate deviation from
  // upstream). An "ok" export whose anchor never fired is not a download, and the caller
  // announces "download started" — so the silent no-op leaves as an error instead.
  if (!downloadDataUrl(dataUrl, exportFilename(title, format))) {
    throw new Error(`${format} export could not start the download`);
  }
}
