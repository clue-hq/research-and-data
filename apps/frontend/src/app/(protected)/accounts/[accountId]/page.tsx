import { ResearchNavigationProvider } from "@/features/accounts/components/research-link";
import { researchContextQuery } from "@/features/accounts/model/research-context";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AccountDetailScreen } from "@/features/accounts/components/account-detail-screen";
import { getAccountDetails } from "@/features/accounts/data/account-details.repository";

export const metadata: Metadata = {
  title: "Account details",
};

export const dynamic = "force-dynamic";

export default async function AccountDetailPage({
  params,
  searchParams,
}: PageProps<"/accounts/[accountId]">) {
  const { accountId } = await params;
  const context = researchContextQuery(await searchParams);
  const account = await getAccountDetails(accountId, undefined, context);

  if (!account) {
    notFound();
  }

  return <ResearchNavigationProvider accountId={accountId} context={context}><AccountDetailScreen account={account} /></ResearchNavigationProvider>;
}
