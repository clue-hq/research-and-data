"use client";

import { usePathname } from "next/navigation";
import { ApplicationShell } from "@/components/shell/application-shell";
import {
  WorkspaceProfileProvider,
  useWorkspaceProfile,
} from "@/components/shell/workspace-profile-context";
import type { WorkspaceProfile } from "../model/workspace-profile";
import type { Account } from "../model/account";
import type { AccountBulkCapabilities } from "../model/bulk-actions";
import { AccountPanelsProvider } from "./account-workspace-shell";
import { AccountsScreen } from "./accounts-screen";
import motion from "./account-motion.module.css";

export function AccountsLayoutShell({
  accounts,
  bulkCapabilities,
  profile: fallbackProfile,
  children,
}: {
  accounts: Account[];
  bulkCapabilities: AccountBulkCapabilities;
  profile: WorkspaceProfile;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const profile = useWorkspaceProfile() ?? fallbackProfile;
  const directoryVisible =
    pathname === "/accounts" ||
    /^\/accounts\/[^/]+\/preview\/?$/.test(pathname);

  return (
    <WorkspaceProfileProvider profile={profile}>
      <AccountPanelsProvider>
        <div className={motion.scope}>
          <ApplicationShell activeHref="/accounts">
            {/* Keep the directory mounted: previews must not reset its scroll,
                column widths, filters, selection, or locally created accounts. */}
            <div className="h-full" hidden={!directoryVisible}>
              <AccountsScreen accounts={accounts} bulkCapabilities={bulkCapabilities} />
            </div>
            {children}
          </ApplicationShell>
        </div>
      </AccountPanelsProvider>
    </WorkspaceProfileProvider>
  );
}
