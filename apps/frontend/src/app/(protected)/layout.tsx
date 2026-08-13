import { getProtectedSessionResult } from "@/features/session/data/session-dal";
import { SessionControls } from "@/features/session/components/session-controls";
import { ProtectedSessionRecoveryScreen } from "@/features/session/components/protected-session-recovery";
import {
  clearWorkspaceSelection,
  selectWorkspace,
} from "@/features/session/data/session-actions";
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
    <ProjectsTransportProvider transport={transport}>
      {session ? (
        <SessionControls
          onWorkspaceChange={selectWorkspace}
          onClearWorkspace={clearWorkspaceSelection}
          session={session}
        />
      ) : null}
      <ProjectApplicationShell>{children}</ProjectApplicationShell>
    </ProjectsTransportProvider>
  );
}
