"use client";

import { usePathname } from "next/navigation";
import { ApplicationShell } from "@/components/shell/application-shell";
import { WorkspaceProfileProvider } from "@/components/shell/workspace-profile-context";
import type { WorkspaceProfile } from "../model/workspace-profile";
import type { Account } from "../model/account";
import { AccountPanelsProvider } from "./account-workspace-shell";
import { AccountsScreen } from "./accounts-screen";
import motion from "./account-motion.module.css";

export function AccountsLayoutShell({ accounts, profile, children }: {
  accounts: Account[];
  profile: WorkspaceProfile;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const directoryVisible = pathname === "/accounts" || /^\/accounts\/[^/]+\/preview\/?$/.test(pathname);

  return (
    <WorkspaceProfileProvider profile={profile}>
      <AccountPanelsProvider>
        <div className={motion.scope}>
          <ApplicationShell activeHref="/accounts">
            {/* Keep the directory mounted: previews must not reset its scroll,
                column widths, filters, selection, or locally created accounts. */}
            <div className="h-full" hidden={!directoryVisible}>
              <AccountsScreen accounts={accounts} />
            </div>
            {children}
          </ApplicationShell>
        </div>
      </AccountPanelsProvider>
    </WorkspaceProfileProvider>
  );
}
