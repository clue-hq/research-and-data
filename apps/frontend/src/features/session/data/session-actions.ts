"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { z } from "zod";
import { requireWorkspaceMembership } from "./session-dal";
import { WORKSPACE_COOKIE } from "../model/session";

const WorkspaceSelectionSchema = z.string().trim().min(1).max(255);

export async function selectWorkspace(formData: FormData): Promise<void> {
  const workspaceId = WorkspaceSelectionSchema.parse(formData.get("workspaceId"));
  await requireWorkspaceMembership(workspaceId);
  const cookieStore = await cookies();
  cookieStore.set(WORKSPACE_COOKIE, workspaceId, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
  });
  revalidatePath("/", "layout");
}

export async function clearWorkspaceSelection(): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.delete(WORKSPACE_COOKIE);
}
