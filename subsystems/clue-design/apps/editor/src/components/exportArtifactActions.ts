"use client";

import type { EditorExportArtifact } from "@/engine/exportRunner";

const PREVIEW_OBJECT_URL_TTL_MS = 5 * 60 * 1000;

export function downloadDataUrl(dataUrl: string | null, filename: string): void {
  if (!dataUrl || typeof document === "undefined") {
    return;
  }
  const anchor = document.createElement("a");
  anchor.download = filename;
  anchor.rel = "noopener";

  let objectUrl: string | null = null;
  try {
    objectUrl = URL.createObjectURL(dataUrlToBlob(dataUrl));
    anchor.href = objectUrl;
  } catch {
    anchor.href = dataUrl;
  }

  document.body.append(anchor);
  anchor.click();
  anchor.remove();

  if (objectUrl) {
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
  }
}

export function openBlankArtifactPreviewWindow(): Window | null {
  if (typeof window === "undefined") {
    return null;
  }
  if (window.navigator.userAgent.toLowerCase().includes("jsdom")) {
    return null;
  }
  try {
    const previewWindow = window.open("about:blank", "_blank");
    if (previewWindow) {
      previewWindow.opener = null;
    }
    return previewWindow;
  } catch {
    return null;
  }
}

export function showArtifactInPreviewWindow(
  previewWindow: Window | null,
  artifact: EditorExportArtifact | null
): boolean {
  if (!previewWindow || !artifact?.data_url) {
    return false;
  }
  try {
    const objectUrl = URL.createObjectURL(dataUrlToBlob(artifact.data_url));
    previewWindow.location.href = objectUrl;
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), PREVIEW_OBJECT_URL_TTL_MS);
    return true;
  } catch (error) {
    try {
      previewWindow.close();
    } catch {
      // The tab may already be unavailable; there is nothing useful to recover.
    }
    console.warn("[lumen-export-preview] failed to open artifact preview", error);
    return false;
  }
}

export function dataUrlToBlob(dataUrl: string): Blob {
  const [metadata, payload] = dataUrl.split(",", 2);
  if (!metadata || payload === undefined) {
    throw new Error("Invalid data URL");
  }
  const mimeType = /^data:([^;,]+)/.exec(metadata)?.[1] ?? "application/octet-stream";
  if (metadata.includes(";base64")) {
    const binary = atob(payload);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return new Blob([bytes], { type: mimeType });
  }
  return new Blob([decodeURIComponent(payload)], { type: mimeType });
}
