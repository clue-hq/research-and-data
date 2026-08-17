"use client";

import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import { useProjectGalleryController } from "../hooks/use-project-gallery-controller";
import type { GalleryArtifact } from "../model/project-gallery";
import { ProjectGalleryView } from "./project-gallery-view";

export function ProjectGallery({
  artifacts,
  onOpenArtifact,
  projectTitle,
  showSkeletons = false,
}: {
  artifacts: ProjectArtifact[];
  onOpenArtifact: (artifact: GalleryArtifact) => void;
  projectTitle?: string;
  showSkeletons?: boolean;
}) {
  const controller = useProjectGalleryController(artifacts);
  return (
    <ProjectGalleryView
      controller={controller}
      onOpenArtifact={onOpenArtifact}
      projectTitle={projectTitle}
      showSkeletons={showSkeletons}
    />
  );
}
