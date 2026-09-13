import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { getProtectedSession } from "@/features/session/data/session-dal";
import { workspaceCookieName } from "@/auth/local-workspace";

export async function GET() {
  // getProtectedSession routes authentication failures through the shared handler
  // (401 → /sign-in, provisioning errors → /access-denied) instead of surfacing a 500.
  const session = await getProtectedSession();
  if (!session) redirect("/");
  const cookieStore = await cookies();
  cookieStore.set(workspaceCookieName(), session.principal.workspace_id, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
  });
  redirect("/");
}
