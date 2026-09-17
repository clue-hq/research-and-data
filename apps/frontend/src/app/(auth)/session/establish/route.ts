import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { getProtectedSession } from "@/features/session/data/session-dal";
import { WORKSPACE_COOKIE } from "@/features/session/model/session";
import { providerSessionToken } from "@/auth/server";
import { ClueAuthenticationError } from "@/auth/errors";
import { acceptSettingsInvitations } from "@/features/settings/data/invitation.repository";

export async function GET(request: Request) {
  const invite = new URL(request.url).searchParams.get("invite") || undefined;
  const token = await providerSessionToken();
  const cookieStore = await cookies();
  const cookieOptions = {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
  };
  if (token) {
    try {
      // An invited identity need not have a Clue membership yet. Accept before
      // the protected-session DAL can send a new user to owner provisioning.
      const accepted = await acceptSettingsInvitations(token, invite);
      if (accepted.workspace_id)
        cookieStore.set(WORKSPACE_COOKIE, accepted.workspace_id, cookieOptions);
    } catch (error) {
      if (error instanceof ClueAuthenticationError && error.status === 401)
        redirect("/sign-in?reason=session_expired");
      // Older/unconfigured installations retain the ordinary sign-in path.
      if (
        invite ||
        !(
          error instanceof ClueAuthenticationError &&
          error.code === "INVITATIONS_UNCONFIGURED"
        )
      ) {
        const query = new URLSearchParams({
          error:
            error instanceof ClueAuthenticationError
              ? error.code
              : "INVITATIONS_UNAVAILABLE",
        });
        if (invite) query.set("token", invite);
        redirect(`/invite/accept?${query}`);
      }
    }
  }
  // getProtectedSession routes authentication failures through the shared handler
  // (401 → /sign-in, provisioning errors → /access-denied) instead of surfacing a 500.
  const session = await getProtectedSession();
  if (!session) redirect("/");
  cookieStore.set(
    WORKSPACE_COOKIE,
    session.principal.workspace_id,
    cookieOptions,
  );
  redirect("/");
}
