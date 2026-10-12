import type { RefObject } from "react";
import type { PendingAnnotation } from "@/features/design-editor/adapter/annotations";
import type { VeilRenderKind } from "@/features/design-editor/adapter/generating-veil";

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
export interface SiteStageBinding {
  canvas: SiteCanvasBinding;
  mounted: boolean;
}

export function siteStageMounted(input: { editorOrigin: string | null; enabled: boolean; warm: boolean }): boolean {
  return input.enabled || (input.warm && input.editorOrigin !== null);
}
