import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AccountActivityScreen } from "@/features/accounts/components/account-workspace-screens";
import { getAccountDetails } from "@/features/accounts/data/account-details.repository";
import { getAccountWorkspace } from "@/features/accounts/data/account-workspace.repository";

export const metadata: Metadata = {
  title: "Account activity",
};

export const dynamic = "force-dynamic";

export default async function AccountActivityPage({
  params,
}: PageProps<"/accounts/[accountId]/activity">) {
  const { accountId } = await params;
  const [account, workspace] = await Promise.all([
    getAccountDetails(accountId),
    getAccountWorkspace(accountId),
  ]);

  if (!account || !workspace) notFound();
  return <AccountActivityScreen account={account} workspace={workspace} />;
}
