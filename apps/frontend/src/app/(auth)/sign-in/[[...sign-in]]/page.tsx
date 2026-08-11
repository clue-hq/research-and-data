import { SignIn } from "@clerk/nextjs";
import { isAuthenticationEnabled } from "@/auth/config";
import { SessionSignOut } from "@/features/session/components/session-sign-out";
import { clearWorkspaceSelection } from "@/features/session/data/session-actions";

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
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <section className="w-full max-w-md rounded-xl border border-[var(--clue-border-neutral)] bg-[var(--clue-background-page)] p-6 shadow-[var(--clue-shadow-low)]">
          <h1 className="text-xl font-medium">Your session has expired</h1>
          <p className="mt-2 text-[var(--clue-content-subtle)]">
            Sign in again to securely reconnect your Clue workspace.
          </p>
          <SessionSignOut
            className="mt-5 h-8 rounded-lg bg-[var(--primary)] px-3 text-sm font-medium text-white disabled:opacity-60"
            label="Sign in again"
            onClearWorkspace={clearWorkspaceSelection}
            pendingLabel="Preparing sign-in…"
          />
        </section>
      </main>
    );
  }
  return (
    <main className="grid min-h-screen place-items-center p-6">
      <SignIn
        fallbackRedirectUrl="/session/establish"
        path="/sign-in"
        routing="path"
      />
    </main>
  );
}
