import { AccountsLayoutShell } from "@/features/accounts/components/accounts-layout-shell";
import { AccountsRecoveryScreen } from "@/features/accounts/components/accounts-recovery-screen";
import { readAccountsResult } from "@/features/accounts/data/accounts-read-result";
import { getWorkspaceProfile } from "@/features/accounts/data/workspace-profile.repository";
import { ProtectedSessionRecoveryScreen } from "@/features/session/components/protected-session-recovery";
import { getProtectedSessionResult } from "@/features/session/data/session-dal";

/**
 * The one shell on `/accounts/**`.
 *
 * The account screens address the signed-in person ("owned by you", the sidebar
 * profile). The platform has no settings feature, so that person is derived from
 * the protected session by the accounts data layer and injected into the shell —
 * never hard-coded in a component.
 */
export default async function AccountsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const sessionResult = await getProtectedSessionResult();
  if (sessionResult.status === "recovery") {
    return <ProtectedSessionRecoveryScreen recovery={sessionResult.recovery} />;
  }
  const profile = getWorkspaceProfile(sessionResult.session);

  const accounts = await readAccountsResult();
  if (accounts.status === "recovery") {
    return <AccountsRecoveryScreen recovery={accounts.recovery} />;
  }

  return (
    <AccountsLayoutShell accounts={accounts.response.data} profile={profile}>
      {children}
    </AccountsLayoutShell>
  );
}
