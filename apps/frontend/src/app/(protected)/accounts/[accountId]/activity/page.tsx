import { ResearchNavigationProvider } from "@/features/accounts/components/research-link";
import { researchContextQuery } from "@/features/accounts/model/research-context";
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
  searchParams,
}: PageProps<"/accounts/[accountId]/activity">) {
  const { accountId } = await params;
  const context = researchContextQuery(await searchParams);
  const [account, workspace] = await Promise.all([
    getAccountDetails(accountId, undefined, context),
    getAccountWorkspace(accountId, undefined, context),
  ]);

  if (!account || !workspace) notFound();
  return <ResearchNavigationProvider accountId={accountId} context={context}><AccountActivityScreen account={account} workspace={workspace} /></ResearchNavigationProvider>;
}
