import { Suspense } from "react";
import { notFound } from "next/navigation";
import { isFrontendPreviewMode } from "@/features/preview/data/preview-mode";
import { WorkspaceScreen } from "@/features/orchestration/components/workspace-screen";
import { PROJECT_ID } from "@/features/orchestration/model/workspace";
export default async function AccountPlanPage({ params, searchParams }: { params: Promise<{projectId:string}>; searchParams: Promise<{view?:string}> }) {
  const [{projectId}, query] = await Promise.all([params, searchParams]);
  if (!isFrontendPreviewMode() || projectId !== PROJECT_ID) notFound();
  const view = query.view === "artifacts" || query.view === "results" ? query.view : "plan";
  return <Suspense><WorkspaceScreen view={view} projectScoped /></Suspense>;
}
