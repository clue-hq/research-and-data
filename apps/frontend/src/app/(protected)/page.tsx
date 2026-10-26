import type { Metadata } from "next";
import { Suspense } from "react";
import { isFrontendPreviewMode } from "@/features/preview/data/preview-mode";
import { WorkspaceScreen } from "@/features/orchestration/components/workspace-screen";
import { ProjectHomeShell } from "@/features/projects/components/project-home-shell";
import { getProjectHome } from "@/features/projects/data/project-workspace.repository";

export const metadata: Metadata = {
  title: "Home",
};

export default async function Home() {
  if (isFrontendPreviewMode()) return <Suspense><WorkspaceScreen view="home" /></Suspense>;
  const data = await getProjectHome();

  return <ProjectHomeShell data={data} />;
}
