import { getProtectedSession } from "@/features/session/data/session-dal";
import { SessionControls } from "@/features/session/components/session-controls";
import {
  clearWorkspaceSelection,
  selectWorkspace,
} from "@/features/session/data/session-actions";
import { resolveChatTransport } from "@/features/projects/data/chat-api";
import { ProjectsTransportProvider } from "@/features/projects/data/projects-transport";

export default async function ProtectedLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const session = await getProtectedSession();
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
      {children}
    </ProjectsTransportProvider>
  );
}
