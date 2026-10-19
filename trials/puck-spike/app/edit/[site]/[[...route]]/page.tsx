import "@puckeditor/core/puck.css";
import type { Data } from "@puckeditor/core";
import { loadBrand } from "@/lib/brands";
import { SHELL_ROUTE, basePathOf, readSite, routeOf, shellAsData } from "@/lib/store";
import { Editor } from "./client";

const EMPTY: Data = { content: [], root: { props: {} } };

export default async function EditPage({
  params,
}: {
  params: Promise<{ site: string; route?: string[] }>;
}) {
  const { site, route } = await params;
  const path = routeOf(route);
  const stored = readSite(site);
  const shellMode = path === SHELL_ROUTE;
  return (
    <Editor
      site={site}
      route={path}
      data={shellMode ? shellAsData(stored) : stored.pages[path] ?? EMPTY}
      brand={loadBrand(stored.brand)}
      options={{ basePath: basePathOf(site), shell: stored.shell, mode: shellMode ? "shell" : "page", site }}
    />
  );
}

export const dynamic = "force-dynamic";
