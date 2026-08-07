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
  const [account, contacts, featuredContact] = await Promise.all([
    getAccountDetails(accountId),
    getAccountContacts(accountId),
    getAccountContact(accountId, "denise-dresser"),
  ]);

  if (!account || !featuredContact) notFound();

  return (
    <AccountContactsScreen
      account={account}
      contacts={contacts}
      featuredContact={featuredContact}
    />
  );
}
