import type { Metadata } from "next";
import { AccountsScreen } from "@/features/accounts/components/accounts-screen";
import { getAccounts } from "@/features/accounts/data/accounts.repository";

export const metadata: Metadata = {
  title: "Accounts",
};

export const dynamic = "force-dynamic";

export default async function AccountsPage() {
  const response = await getAccounts();

  return <AccountsScreen accounts={response.data} meta={response.meta} />;
}
