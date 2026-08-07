import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AccountArtifactsScreen } from "@/features/accounts/components/account-workspace-screens";
import { getAccountDetails } from "@/features/accounts/data/account-details.repository";
import { getAccountWorkspace } from "@/features/accounts/data/account-workspace.repository";

export const metadata: Metadata = {
  title: "Account artifacts",
};

export const dynamic = "force-dynamic";

export default async function AccountArtifactsPage({
  params,
}: PageProps<"/accounts/[accountId]/artifacts">) {
  const { accountId } = await params;
  const [account, workspace] = await Promise.all([
    getAccountDetails(accountId),
    getAccountWorkspace(accountId),
  ]);

  if (!account || !workspace) notFound();
  return <AccountArtifactsScreen account={account} workspace={workspace} />;
}
