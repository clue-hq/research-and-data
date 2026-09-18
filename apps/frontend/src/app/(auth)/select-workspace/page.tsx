import Link from "next/link";
import { redirect } from "next/navigation";
import { selectWorkspaceAndContinue } from "@/features/session/data/session-actions";
import { getWorkspaceSelectionSession, requireWorkspaceMembership } from "@/features/session/data/session-dal";
import { localWorkspaceInstance } from "@/auth/local-workspace";

export default async function SelectWorkspacePage() {
  const instance = localWorkspaceInstance();
  if (instance) {
    await requireWorkspaceMembership(instance.workspaceId);
    redirect("/projects");
  }
  const session = await getWorkspaceSelectionSession();
  if (session.memberships.length === 0) {
    redirect("/access-denied?code=WORKSPACE_FORBIDDEN");
  }

  return (
    <main className="grid min-h-screen place-items-center bg-[var(--clue-background-neutral)] p-6">
      <section
        aria-labelledby="select-workspace-title"
        className="w-full max-w-md rounded-xl border border-[var(--clue-border-neutral)] bg-[var(--clue-background-page)] p-6 shadow-[var(--clue-shadow-low)]"
      >
        <h1 className="text-xl font-medium" id="select-workspace-title">
          Choose a workspace
        </h1>
        <p className="mt-2 text-[var(--clue-content-subtle)]">
          Select the workspace whose Accounts you want to open.
        </p>
        <div className="mt-5 grid gap-2">
          {session.memberships.map((membership) => (
            <form
              action={selectWorkspaceAndContinue}
              key={membership.membership_id}
            >
              <button
                className="flex min-h-10 w-full items-center justify-between rounded-lg border border-[var(--clue-border-neutral)] px-3 py-2 text-left text-sm outline-none hover:bg-[var(--clue-background-hover)] focus-visible:ring-3 focus-visible:ring-[var(--ring)]/50"
                name="workspaceId"
                type="submit"
                value={membership.workspace_id}
              >
                <span>{membership.workspace_name}</span>
                <span className="text-[var(--clue-content-subtle)]">
                  {membership.role_key}
                </span>
              </button>
            </form>
          ))}
        </div>
        <Link className="mt-5 inline-block text-sm underline" href="/sign-out">
          Sign in with a different account
        </Link>
      </section>
    </main>
  );
}
