import type { Metadata } from "next";
import { AccountsRecoveryScreen } from "@/features/accounts/components/accounts-recovery-screen";
import { AccountsScreen } from "@/features/accounts/components/accounts-screen";
import { readAccountBulkCapabilities } from "@/features/accounts/data/bulk-capabilities.repository";
import { readAccountsResult } from "@/features/accounts/data/accounts-read-result";

export const metadata: Metadata = {
  title: "Accounts",
};

export const dynamic = "force-dynamic";

export default async function AccountsPage() {
  const [result, bulkCapabilities] = await Promise.all([
    readAccountsResult({ page: 1, limit: 20 }),
    readAccountBulkCapabilities(),
  ]);
  if (result.status === "recovery") {
    return <AccountsRecoveryScreen recovery={result.recovery} />;
  }
  const { response } = result;

  return (
    <AccountsScreen
      accounts={response.data}
      bulkCapabilities={bulkCapabilities}
      meta={response.meta}
    />
  );
}
