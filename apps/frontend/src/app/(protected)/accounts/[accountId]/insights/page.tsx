import { ResearchNavigationProvider } from "@/features/accounts/components/research-link";
import { researchContextQuery } from "@/features/accounts/model/research-context";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AccountInsightsScreen } from "@/features/accounts/components/account-workspace-screens";
import { getAccountDetails } from "@/features/accounts/data/account-details.repository";
import { getAccountWorkspace } from "@/features/accounts/data/account-workspace.repository";

export const metadata: Metadata = {
  title: "Account insights",
};

export const dynamic = "force-dynamic";

export default async function AccountInsightsPage({
  params,
  searchParams,
}: PageProps<"/accounts/[accountId]/insights">) {
  const { accountId } = await params;
  const context = researchContextQuery(await searchParams);
  const [account, workspace] = await Promise.all([
    getAccountDetails(accountId, undefined, context),
    getAccountWorkspace(accountId, undefined, context),
  ]);

  if (!account || !workspace) notFound();
  return <ResearchNavigationProvider accountId={accountId} context={context}><AccountInsightsScreen account={account} workspace={workspace} /></ResearchNavigationProvider>;
}
