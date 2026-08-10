import type { ProtectedSession } from "../model/session";
import { SessionSignOut } from "./session-sign-out";

export function SessionControls({
  session,
  onWorkspaceChange,
  onClearWorkspace,
}: Readonly<{
  session: ProtectedSession;
  onWorkspaceChange: (formData: FormData) => Promise<void>;
  onClearWorkspace: () => Promise<void>;
}>) {
  return (
    <aside
      aria-label="Session controls"
      className="fixed right-3 top-3 z-[1000] flex items-center gap-2 rounded-lg border border-[var(--clue-border-neutral)] bg-[var(--clue-background-page)] p-2 shadow-[var(--clue-shadow-low)]"
    >
      <form action={onWorkspaceChange} className="flex items-center gap-2">
        <label className="sr-only" htmlFor="clue-workspace-selector">
          Workspace
        </label>
        <select
          className="h-8 rounded-md border border-[var(--clue-border-input)] bg-transparent px-2 text-sm"
          defaultValue={session.principal.workspace_id}
          id="clue-workspace-selector"
          name="workspaceId"
        >
          {session.memberships.map((membership) => (
            <option
              key={membership.membership_id}
              value={membership.workspace_id}
            >
              {membership.workspace_id}
            </option>
          ))}
        </select>
        <button
          className="h-8 rounded-md border border-[var(--clue-border-neutral)] px-3 text-sm"
          type="submit"
        >
          Switch
        </button>
      </form>
      <SessionSignOut
        className="h-8 rounded-md bg-[var(--primary)] px-3 text-sm text-white disabled:opacity-60"
        onClearWorkspace={onClearWorkspace}
      />
    </aside>
  );
}
