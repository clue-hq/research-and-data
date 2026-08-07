import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AccountsScreen } from "@/features/accounts/components/accounts-screen";
import { getAccountDetails } from "@/features/accounts/data/account-details.repository";
import { getAccountPreviewRows } from "@/features/accounts/data/accounts.repository";

export const metadata: Metadata = {
  title: "Account preview",
};

export const dynamic = "force-dynamic";

export default async function AccountPreviewPage({
  params,
}: PageProps<"/accounts/[accountId]/preview">) {
  const { accountId } = await params;
  const [account, accountRows] = await Promise.all([
    getAccountDetails(accountId),
    getAccountPreviewRows(),
  ]);

  if (!account) {
    notFound();
  }

  return (
    <AccountsScreen
      accounts={accountRows}
      previewAccount={account}
    />
  );
}
