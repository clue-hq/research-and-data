import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { requireProviderSessionToken } from "@/auth/server";
import { loadProtectedSession } from "@/features/session/data/session-dal";
import { WORKSPACE_COOKIE } from "@/features/session/model/session";

export async function GET() {
  const token = await requireProviderSessionToken();
  const cookieStore = await cookies();
  const requested = cookieStore.get(WORKSPACE_COOKIE)?.value;
  const session = await loadProtectedSession(token, requested);
  cookieStore.set(WORKSPACE_COOKIE, session.principal.workspace_id, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
  });
  redirect("/");
}
