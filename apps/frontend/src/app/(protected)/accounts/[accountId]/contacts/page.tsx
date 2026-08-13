import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AccountContactsScreen } from "@/features/accounts/components/account-contacts-screen";
import { getAccountContacts } from "@/features/accounts/data/account-contacts.repository";
import { getAccountDetails } from "@/features/accounts/data/account-details.repository";
import { readContactBulkCapabilities } from "@/features/accounts/data/bulk-capabilities.repository";

export const metadata: Metadata = {
  title: "Account contacts",
};

export const dynamic = "force-dynamic";

export default async function AccountContactsPage({
  params,
}: PageProps<"/accounts/[accountId]/contacts">) {
  const { accountId } = await params;
  const [account, contacts, bulkCapabilities] = await Promise.all([
    getAccountDetails(accountId),
    getAccountContacts(accountId),
    readContactBulkCapabilities(accountId),
  ]);

  if (!account) notFound();

  // No profile is fetched here: each row links to the contact's own route, and
  // that route fetches the profile for the id in its params.
  return (
    <AccountContactsScreen
      account={account}
      bulkCapabilities={bulkCapabilities}
      contacts={contacts}
    />
  );
}
