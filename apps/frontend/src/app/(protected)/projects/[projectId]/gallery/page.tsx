import { redirect } from "next/navigation";
import { projectChatHref } from "@/features/chat-shell/model/chat-shell-routes";

interface ProjectGalleryPageProps {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ thread?: string }>;
}

// Phase R (ruling R3): /projects/{id}/gallery is compat-only. With a thread,
// it redirects straight to the canonical chats path with the gallery surface;
// threadless, the Gallery intent rides the absorber as pane state
// (`/projects/{id}?surface=gallery`) so canonicalization lands the user in
// the Gallery of the resolved default thread — only the URL changes (founder
// amendment, 2026-08-17).
export default async function ProjectGalleryPage({
  params,
  searchParams,
}: ProjectGalleryPageProps) {
  const [{ projectId }, query] = await Promise.all([params, searchParams]);
  if (query.thread) {
    redirect(projectChatHref(projectId, query.thread, { surface: "gallery" }));
  }
  redirect(`/projects/${encodeURIComponent(projectId)}?surface=gallery`);
}
