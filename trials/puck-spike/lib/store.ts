// Sites are saved as JSON files; this stands in for a Postgres jsonb column.
import fs from "node:fs";
import path from "node:path";
import type { Data } from "@puckeditor/core";

export type Site = { brand: string; pages: Record<string, Data> };

const DIR = path.join(process.cwd(), "data", "sites");

export function routeOf(segments: string[] | undefined): string {
  return "/" + (segments ?? []).join("/");
}

export function readSite(site: string): Site {
  const file = path.join(DIR, `${site}.json`);
  if (!fs.existsSync(file)) throw new Error(`no site ${site}`);
  return JSON.parse(fs.readFileSync(file, "utf-8")) as Site;
}

export function writePage(site: string, route: string, data: Data): void {
  const current = readSite(site);
  current.pages[route] = data;
  fs.mkdirSync(DIR, { recursive: true });
  fs.writeFileSync(path.join(DIR, `${site}.json`), JSON.stringify(current, null, 2));
}
