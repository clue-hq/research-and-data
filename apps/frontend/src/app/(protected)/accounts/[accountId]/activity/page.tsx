import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AccountActivityScreen } from "@/features/accounts/components/account-workspace-screens";
import { getAccountActivity } from "@/features/accounts/data/account-activity.repository";
import { getAccountDetails } from "@/features/accounts/data/account-details.repository";

export const metadata: Metadata = {
  title: "Account activity",
};

export const dynamic = "force-dynamic";

export default async function AccountActivityPage({
  params,
}: PageProps<"/accounts/[accountId]/activity">) {
  const { accountId } = await params;
  const [account, activity] = await Promise.all([
    getAccountDetails(accountId),
    getAccountActivity(accountId),
  ]);

  if (!account || !activity) notFound();
  return <AccountActivityScreen account={account} activity={activity} />;
}
