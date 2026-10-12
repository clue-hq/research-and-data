import type { RefObject } from "react";
import type { VeilRenderKind } from "@/features/design-editor/adapter/generating-veil";

/** What the stage needs to draw the site canvas. */
export interface SiteCanvasBinding {
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
