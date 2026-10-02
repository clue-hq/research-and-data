import { getProtectedSessionResult } from "@/features/session/data/session-dal";
import { ProtectedSessionRecoveryScreen } from "@/features/session/components/protected-session-recovery";
import { resolveChatTransport } from "@/features/projects/data/chat-api";
import { ProjectsTransportProvider } from "@/features/projects/data/projects-transport";
import { ProjectCatalogInvalidationProvider } from "@/features/projects/model/project-catalog-invalidation";
import { ProjectApplicationShell } from "@/components/shell/application-shell";
import { WorkspaceProfileProvider } from "@/components/shell/workspace-profile-context";
import { WorkspaceSwitcherProvider } from "@/components/shell/workspace-switcher-context";
import { switchWorkspace } from "@/features/session/data/session-actions";
import { roleLabel } from "@/features/session/model/session";
import { workspaceInitials } from "@/features/accounts/model/workspace-profile";
import { ConfirmationProvider } from "@/components/ui/confirmation-card";
import { getSettingsProfile } from "@/features/settings/data/profile.repository";
import { getSettingsWorkspace } from "@/features/settings/data/workspace.repository";
import { shellProfile } from "@/features/settings/model/profile";
import { accountRecoveryFor } from "@/features/accounts/data/accounts-read-result";
import { AccountsRecoveryScreen } from "@/features/accounts/components/accounts-recovery-screen";

export default async function ProtectedLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const sessionResult = await getProtectedSessionResult();
  if (sessionResult.status === "recovery") {
    return <ProtectedSessionRecoveryScreen recovery={sessionResult.recovery} />;
  }
  const { session } = sessionResult;
  // Resolved on the server by the data layer and handed down as a serializable
  // prop: the projects chat repositories run in the browser, and no component
  // may read an environment variable (`docs/architecture/frontend.md`).
  const transport = resolveChatTransport();
  let profile = null;
  if (session) {
    try {
      const [person, workspace] = await Promise.all([
        getSettingsProfile(),
        getSettingsWorkspace(),
      ]);
      profile = { ...shellProfile(person), workspaceName: workspace.name };
    } catch (error) {
      const recovery = accountRecoveryFor(error);
      if (recovery)
        return (
          <AccountsRecoveryScreen
            recovery={recovery}
            section="Workspace"
            retryHref="/"
            standalone
          />
        );
      throw error;
    }
  }
  // The switcher shows the signed-in user's own memberships, by name. Without a
  // session (authentication disabled) there is nothing to switch between; the
  // fixture build keeps its own demo preview.
  const workspaces = (session?.memberships ?? []).map((membership) => ({
    id: membership.workspace_id,
    name: membership.workspace_name,
    initials: workspaceInitials(membership.workspace_name),
    logoUrl: membership.workspace_logo_url ?? null,
    role: roleLabel(membership.role_key),
  }));
  return (
    <ProjectsTransportProvider
      currentUserId={session?.userId ?? null}
      currentWorkspaceId={session?.principal.workspace_id ?? null}
      transport={transport}
    >
      {/* ONE shell-scoped refresh signal for the whole protected tree (spec
          §2.5: every project mutation invalidates so the sidebar and any open
          workspace refetch). It was mounted inside ApplicationShell, which
          gives a provider per shell MOUNT: a screen that renders its own
          ApplicationShell (artifacts, accounts, brand-context, and the
          projects directory/home) got a second, competing provider, so an
          invalidate on one side of that boundary never reached the other.
          Every ApplicationShell mount site is under this layout, so hoisting
          it here loses nobody and leaves exactly one signal. */}
      <ProjectCatalogInvalidationProvider>
        {/* The dev-era SessionControls overlay (workspace UUID switcher + Sign out,
            top-right) is permanently removed — founder order 2026-08-18, superseding
            the R8 leave-as-is ruling. Workspace switching lives at /select-workspace;
            sign-out at /sign-out. */}
        <WorkspaceSwitcherProvider
          activeWorkspaceId={session?.principal.workspace_id ?? null}
          demo={transport.mode === "fixture"}
          onSelect={switchWorkspace}
          workspaces={workspaces}
        >
          <ConfirmationProvider>
            {profile ? (
              <WorkspaceProfileProvider profile={profile}>
                <ProjectApplicationShell>{children}</ProjectApplicationShell>
              </WorkspaceProfileProvider>
            ) : (
              <ProjectApplicationShell>{children}</ProjectApplicationShell>
            )}
          </ConfirmationProvider>
        </WorkspaceSwitcherProvider>
      </ProjectCatalogInvalidationProvider>
    </ProjectsTransportProvider>
  );
}
