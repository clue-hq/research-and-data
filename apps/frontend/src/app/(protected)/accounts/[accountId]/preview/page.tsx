import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AccountsScreen } from "@/features/accounts/components/accounts-screen";
import { readAccountBulkCapabilities } from "@/features/accounts/data/bulk-capabilities.repository";
import { getAccountDetails } from "@/features/accounts/data/account-details.repository";
import { getAccounts } from "@/features/accounts/data/accounts.repository";

export const metadata: Metadata = {
  title: "Account preview",
};

export const dynamic = "force-dynamic";

export default async function AccountPreviewPage({
  params,
}: PageProps<"/accounts/[accountId]/preview">) {
  const { accountId } = await params;
  const [account, accountsResponse, bulkCapabilities] = await Promise.all([
    getAccountDetails(accountId),
    getAccounts({ page: 1, limit: 20 }),
    readAccountBulkCapabilities(),
  ]);

  if (!account) {
    notFound();
  }

  return (
    <AccountsScreen
      accounts={accountsResponse.data}
      bulkCapabilities={bulkCapabilities}
      meta={accountsResponse.meta}
      previewAccount={account}
    />
  );
}
