import type { AgentSectionModule } from "@clue/site-kit";
import type { SectionLink } from "@clue/site-kit/site-document";

export interface LoadedSection {
  digest: string;
  module: AgentSectionModule;
  name: string;
  propsSchema: Record<string, unknown>;
}

export class SectionLoadError extends Error {
  readonly sectionName: string;

  constructor(sectionName: string, reason: string) {
    super(`The section ${sectionName} could not be loaded: ${reason}`);
    this.name = "SectionLoadError";
    this.sectionName = sectionName;
  }
}

export const sectionModuleUrl = (link: SectionLink) => `/sections/${link.digest}.mjs?t=${encodeURIComponent(link.token)}`;
export const sectionStyleUrl = (link: SectionLink) => `/sections/${link.digest}.css?t=${encodeURIComponent(link.token)}`;

export function isSectionModule(value: unknown): value is AgentSectionModule {
  const candidate = value as { render?: unknown; schema?: { safeParse?: unknown } } | null;
  return typeof candidate?.render === "function" && typeof candidate?.schema?.safeParse === "function";
}

export interface SectionLoaderDeps {
  addStylesheet: (digest: string, href: string) => void;
  importModule: (url: string) => Promise<unknown>;
}

/** Contract 4: every section comes from THIS origin's token-checked route (Task 5). One failure
 * fails the whole init, named, so the app shows the canvas error instead of a half page. */
export async function loadSections(links: readonly SectionLink[], deps: SectionLoaderDeps): Promise<LoadedSection[]> {
  return Promise.all(
    links.map(async (link) => {
      deps.addStylesheet(link.digest, sectionStyleUrl(link));
      let imported: unknown;
      try {
        imported = await deps.importModule(sectionModuleUrl(link));
      } catch (cause) {
        throw new SectionLoadError(link.name, cause instanceof Error ? cause.message : String(cause));
      }
      if (!isSectionModule(imported)) throw new SectionLoadError(link.name, "it exports no schema and render");
      return { digest: link.digest, module: imported, name: link.name, propsSchema: link.propsSchema };
    }),
  );
}

export function browserSectionDeps(): SectionLoaderDeps {
  return {
    addStylesheet(digest, href) {
      if (document.head.querySelector(`link[data-section-digest="${digest}"]`)) return;
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = href;
      link.dataset.sectionDigest = digest;
      document.head.appendChild(link);
    },
    // A runtime URL, deliberately not bundled: esbuild leaves a non-literal import() alone.
    importModule: (url) => import(/* webpackIgnore: true */ url),
  };
}
