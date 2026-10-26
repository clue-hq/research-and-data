import { Suspense } from "react";
import { redirect } from "next/navigation";
import { isFrontendPreviewMode } from "@/features/preview/data/preview-mode";
import { projectHref } from "@/features/orchestration/model/workspace";
import { DirectMailScreen } from "@/features/direct-mail/components/direct-mail-screen";

export default async function DirectMailPage({ params }: { params: Promise<{ path?: string[] }> }) {
  const { path } = await params;
  if (isFrontendPreviewMode() && path?.[0] === "project") redirect(projectHref);
  return <Suspense><DirectMailScreen recordId={path?.join("/")} /></Suspense>;
}
