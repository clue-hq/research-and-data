import { redirect } from "next/navigation";
import { isAuthenticationEnabled } from "@/auth/config";
import { SessionExpiredRedirect } from "@/features/session/components/session-expired-redirect";
import { clearWorkspaceSelection } from "@/features/session/data/session-actions";

/**
 * The approved onboarding sign-in card owns normal authentication. This compatibility route
 * is where every expired session lands: it does the FI-2 cleanup automatically, then hands
 * over to the onboarding sign-in page (which shows a one-line "session expired" notice).
 */
export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ reason?: string }>;
}) {
  if (!isAuthenticationEnabled()) {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <p>Authentication is not enabled for this frontend environment.</p>
      </main>
    );
  }
  const { reason } = await searchParams;
  if (reason === "session_expired") {
    // First tries to reconnect a still-live browser session and return to the app.
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <SessionExpiredRedirect onClearWorkspace={clearWorkspaceSelection} />
      </main>
    );
  }
  redirect("/onboarding/sign-in");
}
