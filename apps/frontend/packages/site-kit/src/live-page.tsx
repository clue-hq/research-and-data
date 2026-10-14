// A live site page (publishing live sites, phase 1): what the server draws and the browser takes
// over. The server (render-core, inside the hardened page) and the browser (site-runtime, and the
// render page's own hydration check) draw the SAME tree — SiteRoot around Puck's client Render — so
// React finds exactly the HTML it expects. A tree with an extra component on one side only would move
// React's ids and break the take-over.
import { createElement, useEffect } from "react";
// Importing react-dom/client touches no DOM, so render-core (Node) can import this module too.
import { hydrateRoot } from "react-dom/client";
import { Render, type Config, type Data } from "@puckeditor/core";
import type { AgentSectionModule } from "./agent-kit";
import type { BrandData } from "./brand";
import { makeConfig, SectionBoundary } from "./config";
import type { ShellData } from "./shell";

export type LivePageData = {
  route: string;
  basePath: string;
  title: string;
  page: Data;
  shell: ShellData | null;
  /** Trimmed by brandForPage. */
  brand: BrandData;
  /** Agent section name -> module URL; {} from the renderer, filled by the publisher. */
  sections: Record<string, string>;
};

/** The brand a page needs: everything but the clones it does not use (clones carry captured HTML
 * and CSS and are the bulk of a brand). The shell draws no clone, so it adds none. */
export function brandForPage(brand: BrandData, page: Data, _shell: ShellData | null): BrandData {
  const used = new Set(
    (page.content ?? [])
      .filter((item) => item.type === "ClonedSection")
      .map((item) => String((item.props as { fragmentId?: unknown }).fragmentId ?? "")),
  );
  return { ...brand, clones: Object.fromEntries(Object.entries(brand.clones).filter(([id]) => used.has(id))) };
}

export function SiteRoot({ config, data, onReady }: { config: Config; data: Data; onReady?: () => void }) {
  useEffect(() => onReady?.(), [onReady]);
  return createElement(Render as never, { config, data } as never);
}

/** The config a live page is drawn with — on the server and in the browser alike. */
export function liveConfig(data: LivePageData, agentSections: Record<string, AgentSectionModule>): Config {
  return makeConfig(data.brand, { basePath: data.basePath || undefined, shell: data.shell ?? undefined, agentSections }) as Config;
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
  const config = liveConfig(input.data, input.agentSections);
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
