import type { SiteDocument } from "@clue/site-kit/site-document";
import type { VeilRenderKind } from "@/features/design-editor/adapter/generating-veil";

export const EDITOR_NOT_CONFIGURED = "The website editor is not configured for this environment.";
export const SITE_LOAD_FAILED = "The website could not be loaded.";
/** Review finding S7-2: the editor frame never said it was ready (its domain not served, this app
 * not allowed to frame it, DNS or the certificate missing) — said instead of an endless veil. */
export const EDITOR_DID_NOT_ANSWER =
  "The website editor did not answer. Reload the page; if it keeps happening, the editor's domain is not set up for this environment.";

export interface SiteCanvasInputs {
  documentId: string | null;
  editorOrigin: string | null;
  editorOriginError: string | null;
  editorOriginLoaded: boolean;
  frameError: string | null;
  frameReady: boolean;
  /** The frame on the canvas has not said it is ready within the frame host's wait. */
  frameTimedOut: boolean;
  loadError: string | null;
  loadStatus: "idle" | "loading" | "ready" | "error";
  shownDocumentId: string | null;
  site: SiteDocument | null;
}

export function siteIsEmpty(site: SiteDocument): boolean {
  return Object.values(site.pages).every((page) => page.content.length === 0);
}

/** Which of the web canvas's three states (or the frame itself) the site canvas shows. */
export function siteCanvasState(input: SiteCanvasInputs): { kind: VeilRenderKind; message: string | null } {
  if (!input.documentId) return { kind: "empty", message: null };
  if (input.editorOriginLoaded && !input.editorOrigin) {
    return { kind: "error", message: input.editorOriginError ?? EDITOR_NOT_CONFIGURED };
  }
  if (input.loadStatus === "error") return { kind: "error", message: input.loadError ?? SITE_LOAD_FAILED };
  if (input.frameError) return { kind: "error", message: input.frameError };
  if (input.frameTimedOut) return { kind: "error", message: EDITOR_DID_NOT_ANSWER };
  if (input.site && input.loadStatus === "ready" && siteIsEmpty(input.site)) return { kind: "empty", message: null };
  if (!input.editorOrigin || input.loadStatus !== "ready" || !input.frameReady || input.shownDocumentId !== input.documentId) {
    return { kind: "loading", message: null };
  }
  return { kind: "ready", message: null };
}
