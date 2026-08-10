import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ContactFullScreen } from "@/features/accounts/components/contact-full-screen";
import { getAccountContact } from "@/features/accounts/data/account-contacts.repository";

export const metadata: Metadata = {
  title: "Contact details",
};

export const dynamic = "force-dynamic";

export default async function ContactDetailsPage({
  params,
}: PageProps<"/accounts/[accountId]/contacts/[contactId]">) {
  const { accountId, contactId } = await params;
  const contact = await getAccountContact(accountId, contactId);

  if (!contact) notFound();

  return <ContactFullScreen contact={contact} />;
}
