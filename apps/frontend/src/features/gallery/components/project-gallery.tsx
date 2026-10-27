"use client";

import { useMaterialsEnabled } from "@/features/account-materials/hooks/use-materials-enabled";
import { MaterialsBrowser } from "@/features/account-materials/components/materials-browser";
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
  projectId,
  showSkeletons = false,
  materialsAccount,
  onBackToAccounts,
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
  materialsAccount?:string;
  onBackToAccounts?:()=>void;
}) {
  const controller = useProjectGalleryController(artifacts, documents);
  const enabled=useMaterialsEnabled();
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
  return enabled ? <MaterialsBrowser initialAccount={materialsAccount} projectId={projectId} onBackToAccounts={onBackToAccounts} designFiles={designFiles}/> : designFiles;
}
