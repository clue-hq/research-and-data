import { Suspense } from "react";
import { notFound } from "next/navigation";
import { isFrontendPreviewMode } from "@/features/preview/data/preview-mode";
import { WorkspaceScreen } from "@/features/orchestration/components/workspace-screen";
import { PROJECT_ID } from "@/features/orchestration/model/workspace";

export default async function AccountPlanPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  if (!isFrontendPreviewMode() || projectId !== PROJECT_ID) notFound();
  return <Suspense><WorkspaceScreen /></Suspense>;
}
