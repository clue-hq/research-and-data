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
}: PageProps<"/accounts/[accountId]/preview">) {
  const { accountId } = await params;
  const account = await getAccountDetails(accountId);

  if (!account) {
    notFound();
  }

  return (
    <AccountPreviewDrawer account={account} />
  );
}
