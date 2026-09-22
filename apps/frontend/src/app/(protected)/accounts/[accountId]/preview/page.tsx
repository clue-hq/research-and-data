import { ResearchNavigationProvider } from "@/features/accounts/components/research-link";
import { researchContextQuery } from "@/features/accounts/model/research-context";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AccountPreviewDrawer } from "@/features/accounts/components/account-preview-drawer";
import { getAccountDetails } from "@/features/accounts/data/account-details.repository";

export const metadata: Metadata = {
  title: "Account preview",
};

export const dynamic = "force-dynamic";

export default async function AccountPreviewPage({
  params,
  searchParams,
}: PageProps<"/accounts/[accountId]/preview">) {
  const { accountId } = await params;
  const context = researchContextQuery(await searchParams);
  const account = await getAccountDetails(accountId, undefined, context);

  if (!account) {
    notFound();
  }

  return (
    <ResearchNavigationProvider accountId={accountId} context={context}><AccountPreviewDrawer account={account} /></ResearchNavigationProvider>
  );
}
