"use client";

import { useMaterialsEnabled } from "@/features/account-materials/hooks/use-materials-enabled";
import { ProjectArtifactLibrary } from "@/features/account-materials/components/account-artifact-library";
import { useMemo } from "react";
import type { ProjectDocument } from "@/features/projects/model/project-documents";
import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import { useProjectGalleryController } from "../hooks/use-project-gallery-controller";
import { projectGalleryItems, type GalleryArtifact } from "../model/project-gallery";
import { ProjectGalleryView } from "./project-gallery-view";

export function ProjectGallery({
  artifacts,
  documents,
  documentsLoading = false,
  documentsError,
  onRetryDocuments,
  onOpenArtifact,
  projectTitle,
  projectId,
  showSkeletons = false,
  nativeArtifacts,
}: {
  artifacts: ProjectArtifact[];
  documents?: ProjectDocument[];
  documentsLoading?: boolean;
  documentsError?: string | null;
  onRetryDocuments?: () => void;
  onOpenArtifact: (artifact: GalleryArtifact) => void;
  projectTitle?: string;
  projectId?: string;
  showSkeletons?: boolean;
  nativeArtifacts?: GalleryArtifact[];
}) {
  const controller = useProjectGalleryController(artifacts, documents);
  const enabled=useMaterialsEnabled();
  const native=useMemo(()=>nativeArtifacts??projectGalleryItems(artifacts,documents),[artifacts,documents,nativeArtifacts]);
  const designFiles=(
    <ProjectGalleryView
      controller={controller}
      documentsLoading={documentsLoading}
      documentsError={documentsError}
      onRetryDocuments={onRetryDocuments}
      onOpenArtifact={onOpenArtifact}
      projectTitle={projectTitle}
      projectId={projectId}
      showSkeletons={showSkeletons}
    />
  );
  return enabled ? <ProjectArtifactLibrary projectId={projectId} projectTitle={projectTitle} native={native} onOpenNative={onOpenArtifact} documentsLoading={documentsLoading} documentsError={documentsError} onRetryDocuments={onRetryDocuments}/> : designFiles;
}
