import { readSettingsSection } from "@/features/settings/data/settings-read";
import { AccountsRecoveryScreen } from "@/features/accounts/components/accounts-recovery-screen";
import { notFound, redirect } from "next/navigation";
import { getProtectedSession } from "@/features/session/data/session-dal";
import { SettingsRouteSchema } from "@/features/settings/model/settings";
import { staticSettingsSections } from "@/features/settings/data/static-sections";
import { SettingsScreen } from "@/features/settings/components/settings-screen";
import { ProfileSettings } from "@/features/settings/components/profile-settings";
import { WorkspaceSettings } from "@/features/settings/components/workspace-settings";
import { MembersSettings } from "@/features/settings/components/members-settings";
import { SettingsComingSoon } from "@/features/settings/components/settings-coming-soon";
import { ResearchFieldsOverview } from "@/features/settings/components/research-fields-overview";
import { ResearchFieldsSettings } from "@/features/settings/components/research-fields-settings";
import { researchEntities } from "@/features/settings/model/research-fields";
import { BillingSettings } from "@/features/settings/components/billing-settings";
import { PagesSettings } from "@/features/settings/components/pages-settings";

export default async function SettingsPage({
  params,
}: {
  params: Promise<{ section?: string[] }>;
}) {
  const segments = (await params).section ?? [];
  const parsed = SettingsRouteSchema.safeParse(segments);
  if (!parsed.success) notFound();
  const { section, entity, view } = parsed.data;
  if (section === "data-model" && entity && view === "display") {
    redirect(`/settings/data-model/${entity}/fields`);
  }
  const session = await getProtectedSession();
  const canManage =
    session?.principal.permissions.includes("workspace.manage_members") ??
    false;
  const canManageSettings =
    session?.principal.permissions.includes("workspace.manage_settings") ?? false;
  const result = await readSettingsSection(section, entity);
  let content;
  if (result.section === "recovery") {
    content = (
      <AccountsRecoveryScreen
        recovery={result.recovery}
        section="Settings"
        retryHref={`/settings/${segments.join("/") || "profile"}`}
        standalone
        embedded
      />
    );
  } else
    switch (result.section) {
      case "research-overview":
        content = <ResearchFieldsOverview />;
        break;
      case "research-fields":
        content = <ResearchFieldsSettings
          key={`${session?.principal.workspace_id}:${result.data.entity}:${canManageSettings}`}
          fields={result.data}
          canManage={canManageSettings}
        />;
        break;
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
            canManage={canManageSettings}
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
      case "pages":
        content = (
          <PagesSettings
            key={session?.principal.workspace_id}
            initial={result.data}
            canManage={canManageSettings}
          />
        );
        break;
      default:
        switch (section) {
          case "billing":
            content = (
              <BillingSettings billing={staticSettingsSections.billing} />
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
  return (
    <SettingsScreen
      section={section}
      dataModelEntityName={
        researchEntities.find(
          (item) => item.id === entity,
        )?.name
      }
    >
      {content}
    </SettingsScreen>
  );
}
