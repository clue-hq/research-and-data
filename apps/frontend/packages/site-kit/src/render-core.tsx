// Rendering a stored site to static HTML: the React half of the server render (Wave 2 Lane A).
// Pure — no DOM, no file reads — so it is tested in Node; render-browser.tsx calls it inside the
// design API's hardened Chromium page after loading the site's agent sections.
import { createElement } from "react";
import { renderToStaticMarkup, renderToString } from "react-dom/server";
import { Render } from "@puckeditor/core/rsc";
import type { Config, Data } from "@puckeditor/core";
import { z } from "zod";
import type { AgentSectionModule } from "./agent-kit";
import type { BrandData } from "./brand";
import { makeConfig } from "./config";
import { SiteRoot, brandForPage, liveConfig, type LivePageData } from "./live-page";
import type { ShellData } from "./shell";
import { tailwindThemeCss } from "./theme";

export type StoredSite = { title?: string; pages: Record<string, unknown>; shell: ShellData | null };
/** `data` is the live page's data (live mode only): what the browser takes the page over with. */
export type RenderedSitePage = { route: string; html: string; data?: LivePageData };

/** A render that cannot finish, with one of the contract codes (Contract 3). */
export class RenderRefusal extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
    this.name = "RenderRefusal";
  }
}

const escapeHtml = (value: string) => value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** "/" first, then every other route alphabetically. */
export function siteRoutes(site: StoredSite): string[] {
  const others = Object.keys(site.pages).filter((route) => route !== "/").sort();
  return site.pages["/"] === undefined ? others : ["/", ...others];
}

export function renderSitePages(input: {
  site: StoredSite;
  brand: BrandData;
  /** Where the site is served ("/acme-site"); "" leaves /route links as written. */
  basePath: string;
  routes?: string[];
  agentSections: Record<string, AgentSectionModule>;
  /** Total characters of HTML allowed across the routes rendered. */
  maxOutputBytes: number;
  /** Live mode (publishing live sites): each route is drawn into #clue-site with the tree the
   * browser hydrates, and comes back with its page data. Without it, static HTML as before. */
  live?: boolean;
}): { pages: RenderedSitePage[]; tailwindTheme: string; size: number; warnings: string[] } {
  const config = makeConfig(input.brand, {
    basePath: input.basePath || undefined,
    shell: input.site.shell ?? undefined,
    agentSections: input.agentSections,
  }) as Config;
  const pages: RenderedSitePage[] = [];
  const warnings: string[] = [];
  let size = 0;
  for (const route of input.routes ?? siteRoutes(input.site)) {
    const data = input.site.pages[route] as Data | undefined;
    if (!data) throw new RenderRefusal("render.failed", `the site has no page ${route}`);
    for (const item of (data.content ?? []) as { type: string; props: Record<string, unknown> }[]) {
      if (item.type === "ClonedSection" && !input.brand.clones[String(item.props?.fragmentId ?? "")]) {
        warnings.push(`${route}: cloned section ${String(item.props?.fragmentId)} is not one of the brand's clones`);
      }
    }
    const title = String((data.root as { props?: { title?: string } } | undefined)?.props?.title || input.site.title || "");
    let body: string;
    let pageData: LivePageData | undefined;
    if (input.live) {
      pageData = {
        route,
        basePath: input.basePath,
        title,
        page: data,
        shell: input.site.shell ?? null,
        brand: brandForPage(input.brand, data),
        sections: {},
      };
      // Drawn with the very config the browser builds from this page data, so the two trees match.
      const pageConfig = liveConfig(pageData, input.agentSections);
      body = `<div id="clue-site">${renderToString(createElement(SiteRoot, { config: pageConfig, data }))}</div>`;
    } else {
      body = renderToStaticMarkup(createElement(Render as never, { config, data } as never));
    }
    const html = `<!doctype html><html lang="en"><head><title>${escapeHtml(title)}</title></head><body>${body}</body></html>`;
    size += html.length;
    if (size > input.maxOutputBytes) {
      throw new RenderRefusal("render.output_too_large", `the rendered site passed ${input.maxOutputBytes} characters at ${route}`);
    }
    pages.push(pageData ? { route, html, data: pageData } : { route, html });
  }
  return { pages, tailwindTheme: tailwindThemeCss(input.brand), size, warnings };
}

/** A loaded agent section's props JSON Schema, or the reasons it cannot join a site. The rules are
 * the ones the spike's check-section CLI applied after importing the module; D2 moved them here,
 * where the module is loaded only inside the hardened render page. */
export function sectionPropsSchema(module: { schema?: unknown; render?: unknown }): { props: unknown } | { errors: string[] } {
  const errors: string[] = [];
  let props: unknown = null;
  if (!(module.schema instanceof z.ZodObject)) {
    errors.push("`schema` must be a zod object (z.object({...}).strict())");
  } else {
    const keys = Object.keys(module.schema.shape);
    for (const key of ["className", "style"]) if (keys.includes(key)) errors.push(`the props may not include "${key}"`);
    for (const key of ["id", "surface"]) if (!keys.includes(key)) errors.push(`the props need "${key}" (every section has an id and a surface)`);
    // Review finding K1-2: the editor opens a site only when every section's id is text. Read as
    // the INPUT a stored page holds, so an optional id or one filled by a default is refused too.
    if (keys.includes("id")) {
      const input = z.toJSONSchema(module.schema, { io: "input" }) as { required?: string[]; properties?: Record<string, { type?: unknown }> };
      if (!input.required?.includes("id") || input.properties?.id?.type !== "string") {
        errors.push('"id" must be required text: write `id: z.string()` (no .optional(), no .default(), not a number)');
      }
    }
    props = z.toJSONSchema(module.schema);
  }
  if (typeof module.render !== "function") errors.push("`render` must be a function (props, kit) => JSX");
  return errors.length ? { errors } : { props };
}
