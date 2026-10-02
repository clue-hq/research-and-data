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

/**
 * The web export's filename. The design API already names the zip
 * (`Content-Disposition: attachment; filename="<slug>-<id8>.zip"`) and the BFF
 * forwards that header, so its name wins whenever it arrives; the sanitized
 * title is only the fallback for a response that carries none.
 */
export function webExportFilename(title: string, contentDisposition: string | null): string {
  const named = /filename\*?=(?:"([^"]*)"|([^;]+))/i.exec(contentDisposition ?? "");
  const fromHeader = (named?.[1] ?? named?.[2] ?? "").trim();
  if (fromHeader) return fromHeader;
  const sanitized = title
    .replace(/[\\/:*?"<>|]+|[\u0000-\u001f\u007f]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return `${sanitized || "website"}.zip`;
}

/**
 * The web artifact's one download: the design API's self-contained static-site
 * zip (founder ruling 2026-09-16), fetched through the same BFF every other
 * design call uses. A refusal arrives as the API's own JSON `detail.message`
 * and leaves as an Error — this layer swallows nothing.
 */
export async function exportWebArtifact(documentId: string, title: string): Promise<void> {
  const { apiBaseUrl, fetchImpl } = designBffConfig();
  const response = await fetchImpl!(
    new URL(`/documents/${encodeURIComponent(documentId)}/web/export`, apiBaseUrl),
  );
  if (!response.ok) {
    const detail = await response
      .json()
      .then((body: unknown) => (body as { detail?: { message?: string } })?.detail)
      .catch(() => undefined);
    throw new Error(detail?.message ?? `Export failed (HTTP ${response.status})`);
  }
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = webExportFilename(title, response.headers.get("content-disposition"));
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // The object URL outlives the click by a tick: revoking it synchronously can
  // cancel the download the click just started.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
