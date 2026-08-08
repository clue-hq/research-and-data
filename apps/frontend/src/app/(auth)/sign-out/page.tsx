import Link from "next/link";
import { isAuthenticationEnabled } from "@/auth/config";
import { SessionSignOut } from "@/features/session/components/session-sign-out";
import { clearWorkspaceSelection } from "@/features/session/data/session-actions";

export default function SignOutPage() {
  if (!isAuthenticationEnabled()) {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <Link href="/">Return to Clue</Link>
      </main>
    );
  }
  return (
    <main className="grid min-h-screen place-items-center p-6">
      <SessionSignOut onClearWorkspace={clearWorkspaceSelection} />
    </main>
  );
}
