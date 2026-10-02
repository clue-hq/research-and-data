"use client";

import type { ProjectDocument } from "@/features/projects/model/project-documents";
import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import { useProjectGalleryController } from "../hooks/use-project-gallery-controller";
import type { GalleryArtifact } from "../model/project-gallery";
import { ProjectGalleryView } from "./project-gallery-view";

export function ProjectGallery({
  artifacts,
  documents,
  documentsLoading = false,
  documentsError,
  onRetryDocuments,
  onOpenArtifact,
  projectTitle,
  showSkeletons = false,
}: {
  artifacts: ProjectArtifact[];
  documents?: ProjectDocument[];
  documentsLoading?: boolean;
  documentsError?: string | null;
  onRetryDocuments?: () => void;
  onOpenArtifact: (artifact: GalleryArtifact) => void;
  projectTitle?: string;
  showSkeletons?: boolean;
}) {
  const controller = useProjectGalleryController(artifacts, documents);
  return (
    <ProjectGalleryView
      controller={controller}
      documentsLoading={documentsLoading}
      documentsError={documentsError}
      onRetryDocuments={onRetryDocuments}
      onOpenArtifact={onOpenArtifact}
      projectTitle={projectTitle}
      showSkeletons={showSkeletons}
    />
  );
}
