import { readSettingsSection } from "@/features/settings/data/settings-read";
import { AccountsRecoveryScreen } from "@/features/accounts/components/accounts-recovery-screen";
import { notFound } from "next/navigation";
import { getProtectedSession } from "@/features/session/data/session-dal";
import { SettingsSectionSchema } from "@/features/settings/model/settings";
import { staticSettingsSections } from "@/features/settings/data/static-sections";
import { SettingsScreen } from "@/features/settings/components/settings-screen";
import { ProfileSettings } from "@/features/settings/components/profile-settings";
import { WorkspaceSettings } from "@/features/settings/components/workspace-settings";
import { MembersSettings } from "@/features/settings/components/members-settings";
import { SettingsComingSoon } from "@/features/settings/components/settings-coming-soon";
import { StaticSettingsOverlay } from "@/features/settings/components/static-settings-overlay";
import { BillingSettings } from "@/features/settings/components/billing-settings";
import { PagesSettings } from "@/features/settings/components/pages-settings";

export default async function SettingsPage({
  params,
}: {
  params: Promise<{ section?: string[] }>;
}) {
  const segments = (await params).section ?? [];
  const parsed = SettingsSectionSchema.safeParse(segments[0] ?? "profile");
  if (!parsed.success || segments.length > 1 || parsed.data === "data-model")
    notFound();
  const section = parsed.data;
  const session = await getProtectedSession();
  const canManage =
    session?.principal.permissions.includes("workspace.manage_members") ??
    false;
  const result = await readSettingsSection(section);
  let content;
  if (result.section === "recovery") {
    content = (
      <AccountsRecoveryScreen
        recovery={result.recovery}
        section="Settings"
        retryHref={`/settings/${section}`}
        standalone
        embedded
      />
    );
  } else
    switch (result.section) {
      case "profile":
        content = (
          <ProfileSettings key={result.data.user_id} profile={result.data} />
        );
        break;
      case "workspace":
        content = (
          <WorkspaceSettings
            key={result.data.workspace_id}
            workspace={result.data}
            canManage={canManage}
          />
        );
        break;
      case "members":
        content = (
          <MembersSettings
            key={session?.principal.workspace_id}
            members={result.data}
            canManage={canManage}
          />
        );
        break;
      default:
        switch (section) {
          case "billing":
            content = (
              <StaticSettingsOverlay>
                <BillingSettings billing={staticSettingsSections.billing} />
              </StaticSettingsOverlay>
            );
            break;
          case "pages":
            content = (
              <StaticSettingsOverlay>
                <PagesSettings pages={staticSettingsSections.pages} />
              </StaticSettingsOverlay>
            );
            break;
          default:
            content = (
              <SettingsComingSoon
                section={
                  section as "connections" | "mcp-server" | "integrations"
                }
                connections={staticSettingsSections.connections}
              />
            );
        }
    }
  return <SettingsScreen section={section}>{content}</SettingsScreen>;
}
