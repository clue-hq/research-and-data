import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AccountContactsScreen } from "@/features/accounts/components/account-contacts-screen";
import { getAccountContacts } from "@/features/accounts/data/account-contacts.repository";
import { getAccountDetails } from "@/features/accounts/data/account-details.repository";

export const metadata: Metadata = {
  title: "Account contacts",
};

export const dynamic = "force-dynamic";

export default async function AccountContactsPage({
  params,
}: PageProps<"/accounts/[accountId]/contacts">) {
  const { accountId } = await params;
  const [account, contacts] = await Promise.all([
    getAccountDetails(accountId),
    getAccountContacts(accountId),
  ]);
  if (!account) notFound();

  // No contact is "featured": the drawer opens on a row click and loads that
  // row's detail then (source map §6). The page used to scan the list for the
  // first previewable row and prefetch its whole detail payload.
  return <AccountContactsScreen account={account} contacts={contacts} />;
}
