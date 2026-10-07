import { Render } from "@puckeditor/core/rsc";
import { notFound } from "next/navigation";
import { loadBrand } from "@/lib/brands";
import { readSite, routeOf } from "@/lib/store";
import { makeConfig } from "@/puck/config";

// Published page: rendered on the server, no editor code shipped.
export default async function PublishedPage({
  params,
}: {
  params: Promise<{ site: string; route?: string[] }>;
}) {
  const { site, route } = await params;
  const stored = readSite(site);
  const data = stored.pages[routeOf(route)];
  if (!data) notFound();
  return <Render config={makeConfig(loadBrand(stored.brand))} data={data} />;
}

export const dynamic = "force-dynamic";
