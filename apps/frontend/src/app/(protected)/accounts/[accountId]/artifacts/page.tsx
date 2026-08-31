import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AccountArtifactsScreen } from "@/features/accounts/components/account-workspace-screens";
import { getAccountDetails } from "@/features/accounts/data/account-details.repository";

export const metadata: Metadata = {
  title: "Account artifacts",
};

export const dynamic = "force-dynamic";

export default async function AccountArtifactsPage({
  params,
}: PageProps<"/accounts/[accountId]/artifacts">) {
  const { accountId } = await params;
  const account = await getAccountDetails(accountId);

  if (!account) notFound();
  return (
    <AccountArtifactsScreen account={account} state="capability_unavailable" />
  );
}
