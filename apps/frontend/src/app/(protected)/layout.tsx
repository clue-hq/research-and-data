import { getProtectedSessionResult } from "@/features/session/data/session-dal";
import { ProtectedSessionRecoveryScreen } from "@/features/session/components/protected-session-recovery";
import { resolveChatTransport } from "@/features/projects/data/chat-api";
import { ProjectsTransportProvider } from "@/features/projects/data/projects-transport";
import { ProjectApplicationShell } from "@/components/shell/application-shell";

export default async function ProtectedLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const sessionResult = await getProtectedSessionResult();
  if (sessionResult.status === "recovery") {
    return (
      <ProtectedSessionRecoveryScreen recovery={sessionResult.recovery} />
    );
  }
  const { session } = sessionResult;
  // Resolved on the server by the data layer and handed down as a serializable
  // prop: the projects chat repositories run in the browser, and no component
  // may read an environment variable (`docs/architecture/frontend.md`).
  const transport = resolveChatTransport();
  return (
    <ProjectsTransportProvider
      currentUserId={session?.userId ?? null}
      currentWorkspaceId={session?.principal.workspace_id ?? null}
      transport={transport}
    >
      {/* The dev-era SessionControls overlay (workspace UUID switcher + Sign out,
          top-right) is permanently removed — founder order 2026-08-18, superseding
          the R8 leave-as-is ruling. Workspace switching lives at /select-workspace;
          sign-out at /sign-out. */}
      <ProjectApplicationShell>{children}</ProjectApplicationShell>
    </ProjectsTransportProvider>
  );
}
