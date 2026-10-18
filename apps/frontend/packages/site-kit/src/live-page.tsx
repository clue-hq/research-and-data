// A live site page (publishing live sites, phase 1): what the server draws and the browser takes
// over. The server (render-core, inside the hardened page) and the browser (site-runtime, and the
// render page's own hydration check) draw the SAME tree — SiteRoot around Puck's render-only Render
// (`@puckeditor/core/rsc`: a plain component, so the page's runtime carries none of the editor) — so
// React finds exactly the HTML it expects. A tree with an extra component on one side only would move
// React's ids and break the take-over.
import { createElement, useEffect } from "react";
// Importing react-dom/client touches no DOM, so render-core (Node) can import this module too.
import { hydrateRoot } from "react-dom/client";
import type { Config, Data } from "@puckeditor/core";
import { Render } from "@puckeditor/core/rsc";
import type { AgentSectionModule } from "./agent-kit";
import type { BrandData } from "./brand";
import { makeConfig, SectionBoundary, type CloneHtml } from "./config";

export type LivePageData = {
  route: string;
  basePath: string;
  title: string;
  /** The page with the header first and the footer last (plan 6: shell-entries.ts). */
  page: Data;
  /** Trimmed by brandForPage. */
  brand: BrandData;
  /** Agent section name -> module URL; {} from the renderer, filled by the publisher. */
  sections: Record<string, string>;
  /** The markup the server drew for each cloned section, by component id: the browser draws exactly
   * this, so its runtime needs no HTML parser and a redraw keeps every clone. */
  cloneHtml: Record<string, string>;
};

/** The brand the browser needs for a page: only the clones the page uses, and those without their
 * captured HTML and CSS, the bulk of a brand — the browser draws each clone from the page data's
 * `cloneHtml`, and their CSS is one stylesheet outside the tree. The page's data includes the header
 * and footer, so a template header's clone is among them. */
export function brandForPage(brand: BrandData, page: Data): BrandData {
  const used = new Set(
    (page.content ?? [])
      .filter((item) => item.type === "ClonedSection")
      .map((item) => String((item.props as { fragmentId?: unknown }).fragmentId ?? "")),
  );
  return {
    ...brand,
    clones: Object.fromEntries(
      Object.entries(brand.clones)
        .filter(([id]) => used.has(id))
        .map(([id, clone]) => [id, { ...clone, html: "", css: "" }]),
    ),
  };
}

export function SiteRoot({ config, data, onReady }: { config: Config; data: Data; onReady?: () => void }) {
  useEffect(() => onReady?.(), [onReady]);
  return createElement(Render as never, { config, data } as never);
}

/** The config a live page is drawn with — on the server and in the browser alike, from the same
 * page data. `cloneHtml` is the one difference: the server fills each clone (and records what it
 * drew into the page data), the browser draws what was recorded (`drawnCloneHtml`). */
export function liveConfig(data: LivePageData, agentSections: Record<string, AgentSectionModule>, cloneHtml: CloneHtml): Config {
  return makeConfig(data.brand, {
    basePath: data.basePath || undefined,
    agentSections,
    cloneHtml,
    cloneCss: "page",
  }) as Config;
}

/** The browser's clone markup: what the server drew for that section. */
export function drawnCloneHtml(data: LivePageData): CloneHtml {
  return (_clone, _values, _replacements, _links, { id }) => data.cloneHtml[id] ?? "";
}

/** Takes the server's HTML in `container` over. `ready` resolves after the first commit (or once the
 * whole page has failed); every
 * mismatch, every error a section boundary caught (named by its section) and every uncaught error
 * goes to `report`. */
export function hydrateSite(input: {
  container: Element;
  data: LivePageData;
  agentSections: Record<string, AgentSectionModule>;
  report: (message: string) => void;
}): { ready: Promise<void>; unmount: () => void } {
  const config = liveConfig(input.data, input.agentSections, drawnCloneHtml(input.data));
  const message = (error: unknown) => (error instanceof Error ? error.message : String(error));
  let resolve: () => void = () => undefined;
  const ready = new Promise<void>((done) => (resolve = done));
  const root = hydrateRoot(input.container, createElement(SiteRoot, { config, data: input.data.page, onReady: () => resolve() }), {
    onRecoverableError: (error) => input.report(`mismatch: ${message(error)}`),
    // React reports a caught error before the boundary's own componentDidCatch runs, so the section
    // is named here, from the boundary that caught it.
    onCaughtError: (error, info) => {
      const section = info.errorBoundary instanceof SectionBoundary ? `${info.errorBoundary.props.name}: ` : "";
      input.report(`section failed: ${section}${message(error)}`);
    },
    // A page that fails outright never commits, so `ready` settles here too rather than never.
    onUncaughtError: (error) => {
      input.report(`page failed: ${message(error)}`);
      resolve();
    },
  });
  return { ready, unmount: () => root.unmount() };
}
