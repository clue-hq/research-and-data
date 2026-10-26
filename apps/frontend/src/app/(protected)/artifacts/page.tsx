import type { Metadata } from "next";
import { ArtifactLibrary } from "@/features/artifacts/components/artifact-library";
import { getArtifactLibrary } from "@/features/artifacts/data/artifact-library.repository";

export const metadata: Metadata = { title: "Artifacts" };
// The library is read per request: a save, rename or archive answers with
// `router.refresh()`, and a cached render would show the state before it.
export const dynamic = "force-dynamic";

export default async function ArtifactsPage() {
  return <ArtifactLibrary data={await getArtifactLibrary()} />;
}
