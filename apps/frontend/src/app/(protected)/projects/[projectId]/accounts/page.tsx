import { redirect } from "next/navigation";
import { projectTargetAccountsHref } from "@/features/chat-shell/model/chat-shell-routes";

export default async function ProjectAccountsPage({ params, searchParams }: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ thread?: string }>;
}) {
  const [{ projectId }, { thread }] = await Promise.all([params, searchParams]);
  redirect(projectTargetAccountsHref(projectId, thread));
}
