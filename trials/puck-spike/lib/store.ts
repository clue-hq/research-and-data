// Sites are saved as JSON files; this stands in for a Postgres jsonb column.
import fs from "node:fs";
import path from "node:path";
import type { Data } from "@puckeditor/core";
import type { ShellData } from "@/puck/shell";

export type Site = { brand: string; shell?: ShellData; pages: Record<string, Data> };

export const SHELL_ROUTE = "/_shell";
const DIR = path.join(process.cwd(), "data", "sites");

export function routeOf(segments: string[] | undefined): string {
  return "/" + (segments ?? []).join("/");
}

export const basePathOf = (site: string) => `/s/${site}`;

export function readSite(site: string): Site {
  const file = path.join(DIR, `${site}.json`);
  if (!fs.existsSync(file)) throw new Error(`no site ${site}`);
  return JSON.parse(fs.readFileSync(file, "utf-8")) as Site;
}

function writeSite(site: string, data: Site): void {
  fs.mkdirSync(DIR, { recursive: true });
  fs.writeFileSync(path.join(DIR, `${site}.json`), JSON.stringify(data, null, 2));
}

export function writePage(site: string, route: string, data: Data): void {
  const current = readSite(site);
  if (route === SHELL_ROUTE) {
    const header = data.content.find((item) => item.type === "SiteHeader")?.props;
    const footer = data.content.find((item) => item.type === "SiteFooter")?.props;
    current.shell = {
      header: { ...(current.shell?.header ?? {}), ...(header ?? {}) },
      footer: { ...(current.shell?.footer ?? {}), ...(footer ?? {}) },
    } as ShellData;
  } else {
    current.pages[route] = data;
  }
  writeSite(site, current);
}

/** The shell as editable Puck data: one header block and one footer block. */
export function shellAsData(site: Site): Data {
  return {
    root: { props: {} },
    content: [
      { type: "SiteHeader", props: { id: "site-header", ...(site.shell?.header ?? {}) } },
      { type: "SiteFooter", props: { id: "site-footer", ...(site.shell?.footer ?? {}) } },
    ],
  } as Data;
}
