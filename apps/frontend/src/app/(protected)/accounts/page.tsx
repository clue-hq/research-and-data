import type { Metadata } from "next";
import { AccountsRecoveryScreen } from "@/features/accounts/components/accounts-recovery-screen";
import { AccountsScreen } from "@/features/accounts/components/accounts-screen";
import { readAccountsResult } from "@/features/accounts/data/accounts-read-result";

export const metadata: Metadata = {
  title: "Accounts",
};

export const dynamic = "force-dynamic";

export default async function AccountsPage() {
  const result = await readAccountsResult();
  if (result.status === "recovery") {
    return <AccountsRecoveryScreen recovery={result.recovery} />;
  }
  const { response } = result;

  return <AccountsScreen accounts={response.data} meta={response.meta} />;
}
