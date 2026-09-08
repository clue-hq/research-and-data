import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ContactFullScreen } from "@/features/accounts/components/contact-full-screen";
import { getAccountContact } from "@/features/accounts/data/account-contacts.repository";
import { getAccountDetails } from "@/features/accounts/data/account-details.repository";

export const metadata: Metadata = {
  title: "Contact details",
};

export const dynamic = "force-dynamic";

export default async function ContactDetailsPage({
  params,
}: PageProps<"/accounts/[accountId]/contacts/[contactId]">) {
  const { accountId, contactId } = await params;
  const [account, contact] = await Promise.all([
    getAccountDetails(accountId),
    getAccountContact(accountId, contactId),
  ]);

  if (!account || !contact) notFound();

  return <ContactFullScreen account={account} contact={contact} />;
}
