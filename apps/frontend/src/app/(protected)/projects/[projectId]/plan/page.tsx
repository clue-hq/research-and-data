import { redirect, notFound } from "next/navigation";
import { isFrontendPreviewMode } from "@/features/preview/data/preview-mode";
import { PROJECT_ID, chatHref } from "@/features/orchestration/model/workspace";
export default async function AccountPlanPage({params}:{params:Promise<{projectId:string}>}) {
 const {projectId}=await params;
 if(!isFrontendPreviewMode() || projectId!==PROJECT_ID)notFound();
 redirect(`${chatHref}?surface=target-accounts`);
}
