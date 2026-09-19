"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";
import { requireWorkspaceMembership } from "./session-dal";
import { workspaceCookieName } from "@/auth/local-workspace";

const WorkspaceSelectionSchema = z.string().trim().min(1).max(255);

export async function selectWorkspace(formData: FormData): Promise<void> {
  const workspaceId = WorkspaceSelectionSchema.parse(formData.get("workspaceId"));
  await requireWorkspaceMembership(workspaceId);
  const cookieStore = await cookies();
  cookieStore.set(workspaceCookieName(), workspaceId, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
  });
  revalidatePath("/", "layout");
}

export async function clearWorkspaceSelection(): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.delete(workspaceCookieName());
}

export async function selectWorkspaceAndContinue(
  formData: FormData,
): Promise<void> {
  await selectWorkspace(formData);
  redirect("/");
}

/**
 * The sidebar switcher's selection. Same semantics as the chooser — the
 * membership is re-checked, the cookie is rewritten, and the app is re-entered
 * at its home so nothing stays on a page belonging to the previous workspace.
 */
export async function switchWorkspace(workspaceId: string): Promise<void> {
  const selection = new FormData();
  selection.set("workspaceId", workspaceId);
  await selectWorkspace(selection);
  redirect("/");
}
