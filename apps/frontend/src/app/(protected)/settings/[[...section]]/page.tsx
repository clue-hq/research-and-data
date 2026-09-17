import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ConfirmationCardProvider } from "@/components/ui/confirmation-card";
import { SettingsScreen } from "@/features/settings/components/settings-screen";
import { getPagesSettings } from "@/features/settings/data/pages.repository";
import { getSettingsFixture } from "@/features/settings/data/settings.repository";
import { SettingsRouteSchema } from "@/features/settings/model/settings";
import { getProtectedSession } from "@/features/session/data/session-dal";

export const metadata: Metadata = { title: "Settings" };
export const dynamic = "force-dynamic";

export default async function SettingsPage({
  params,
}: {
  params: Promise<{ section?: string[] }>;
}) {
  const route = SettingsRouteSchema.safeParse((await params).section ?? []);
  if (!route.success) notFound();
  const [session, workspace] = await Promise.all([
    getProtectedSession(),
    getSettingsFixture(),
  ]);
  const canManage =
    session?.principal.permissions.includes("workspace.manage_settings") ?? false;
  const pages = route.data.section === "pages" ? await getPagesSettings() : null;
  return (
    <ConfirmationCardProvider>
      <SettingsScreen
        canManage={canManage}
        pages={pages}
        route={route.data}
        workspace={workspace}
      />
    </ConfirmationCardProvider>
  );
}
