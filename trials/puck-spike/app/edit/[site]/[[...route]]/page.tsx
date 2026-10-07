import "@puckeditor/core/puck.css";
import type { Data } from "@puckeditor/core";
import { loadBrand } from "@/lib/brands";
import { readSite, routeOf } from "@/lib/store";
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
  return (
    <Editor site={site} route={path} data={stored.pages[path] ?? EMPTY} brand={loadBrand(stored.brand)} />
  );
}

export const dynamic = "force-dynamic";
