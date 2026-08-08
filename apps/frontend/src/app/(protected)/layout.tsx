import { getProtectedSession } from "@/features/session/data/session-dal";
import { SessionControls } from "@/features/session/components/session-controls";
import { selectWorkspace } from "@/features/session/data/session-actions";

export default async function ProtectedLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const session = await getProtectedSession();
  return (
    <>
      {session ? (
        <SessionControls
          onWorkspaceChange={selectWorkspace}
          session={session}
        />
      ) : null}
      {children}
    </>
  );
}
