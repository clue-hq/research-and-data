import { redirect } from "next/navigation";
import { isAuthenticationEnabled } from "@/auth/config";
import { SessionExpiredCard } from "@/features/session/components/session-expired-card";
import { clearWorkspaceSelection } from "@/features/session/data/session-actions";

/**
 * The approved onboarding sign-in card owns normal authentication. This compatibility route
 * keeps the explicit expired-session cleanup added by FI-2 before handing ordinary sign-in to
 * the headless-Clerk onboarding flow.
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
    // The card first tries to reconnect a still-live browser session and return to the app.
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <SessionExpiredCard onClearWorkspace={clearWorkspaceSelection} />
      </main>
    );
  }
  redirect("/onboarding/sign-in");
}
