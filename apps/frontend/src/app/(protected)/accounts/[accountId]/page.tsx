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
}: PageProps<"/accounts/[accountId]">) {
  const { accountId } = await params;
  const account = await getAccountDetails(accountId);

  if (!account) {
    notFound();
  }

  return <AccountDetailScreen account={account} />;
}
