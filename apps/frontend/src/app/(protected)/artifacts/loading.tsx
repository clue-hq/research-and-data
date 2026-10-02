import { ApplicationShell } from "@/components/shell/application-shell";
import { GalleryArtifactSkeleton } from "@/features/gallery/components/gallery-artifact-card";
export default function Loading() {
  return (
    <ApplicationShell activeHref="/artifacts">
      <main
        aria-busy="true"
        aria-label="Loading artifacts"
        className="p-8 pt-16"
      >
        <h1 className="mb-8 text-xl">Artifacts</h1>
        <div className="grid grid-cols-2 gap-5 md:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => (
            <GalleryArtifactSkeleton key={i} />
          ))}
        </div>
      </main>
    </ApplicationShell>
  );
}
