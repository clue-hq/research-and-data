import type { RefObject } from "react";
import type { ArtifactVersionsBinding } from "@/features/chat-shell/model/artifact-actions";
import type { PendingAnnotation } from "@/features/design-editor/adapter/annotations";
import type { VeilRenderKind } from "@/features/design-editor/adapter/generating-veil";
import type { SitePageRow, SiteUrlBinding } from "./site-pages";

/** The comment box's half of the web lane's annotation binding (badges are not drawn in a site). */
export interface SiteCanvasAnnotations {
  add: (note?: string) => void;
  dismiss: () => void;
  editNote: (note: string) => void;
  onSend?: (note: string) => void;
  pending: PendingAnnotation | null;
}

/** What the stage needs to draw the site canvas. */
export interface SiteCanvasBinding {
  annotations: SiteCanvasAnnotations | null;
  /** Edit mode, unlocked: the comment box opens only then. */
  editing: boolean;
  errorMessage: string | null;
  iframeRef: RefObject<HTMLIFrameElement | null>;
  renderKind: VeilRenderKind;
  src: string | null;
}

/** The persistent site stage: mounted while a site is open, or warm (the project has a site or an
 * open design leg) once the workspace has an editor origin. Later tasks add pages and the URL bar. */
/** What the Share menu needs from the site editor before it publishes (K6-2). */
export interface SitePublishBinding {
  /** Waits for every edit on its way (typing the frame has not sent yet, then the saves) and says
   * whether they all landed — or why one did not. */
  prepare: (documentId: string) => Promise<SitePublishReadiness>;
  /** The version the editor last saved or loaded, or null before the first load. */
  version: number | null;
}

export type SitePublishReadiness = { ok: true; version: number | null } | { ok: false; message: string };

export interface SiteStageBinding {
  canvas: SiteCanvasBinding;
  mounted: boolean;
  pages: { open: (route: string) => void; rows: SitePageRow[] };
  publish: SitePublishBinding;
  url: SiteUrlBinding;
  versions: ArtifactVersionsBinding | null;
}

export function siteStageMounted(input: { editorOrigin: string | null; enabled: boolean; warm: boolean }): boolean {
  return input.enabled || (input.warm && input.editorOrigin !== null);
}
