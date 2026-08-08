import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AccountContactsScreen } from "@/features/accounts/components/account-contacts-screen";
import {
  getAccountContact,
  getAccountContacts,
} from "@/features/accounts/data/account-contacts.repository";
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

  // The preview drawer needs one full profile. It is the first resolved
  // committee member, not a hard-coded id: an account with an empty committee
  // is a legitimate 200 and must still render its table.
  const featuredContact = contacts.length
    ? await getAccountContact(accountId, contacts[0].id)
    : null;

  return (
    <AccountContactsScreen
      account={account}
      contacts={contacts}
      featuredContact={featuredContact}
    />
  );
}
