// Rendering a stored site to static HTML: the React half of the server render (Wave 2 Lane A).
// Pure — no DOM, no file reads — so it is tested in Node; render-browser.tsx calls it inside the
// design API's hardened Chromium page after loading the site's agent sections.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Render } from "@puckeditor/core/rsc";
import type { Config, Data } from "@puckeditor/core";
import { z } from "zod";
import type { AgentSectionModule } from "./agent-kit";
import type { BrandData } from "./brand";
import { makeConfig } from "./config";
import type { ShellData } from "./shell";
import { tailwindThemeCss } from "./theme";

export type StoredSite = { title?: string; pages: Record<string, unknown>; shell: ShellData | null };
export type RenderedSitePage = { route: string; html: string };

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
    const body = renderToStaticMarkup(createElement(Render as never, { config, data } as never));
    const html = `<!doctype html><html lang="en"><head><title>${escapeHtml(title)}</title></head><body>${body}</body></html>`;
    size += html.length;
    if (size > input.maxOutputBytes) {
      throw new RenderRefusal("render.output_too_large", `the rendered site passed ${input.maxOutputBytes} characters at ${route}`);
    }
    pages.push({ route, html });
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
    props = z.toJSONSchema(module.schema);
  }
  if (typeof module.render !== "function") errors.push("`render` must be a function (props, kit) => JSX");
  return errors.length ? { errors } : { props };
}
