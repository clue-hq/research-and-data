import { ResearchNavigationProvider } from "@/features/accounts/components/research-link";
import { researchContextQuery } from "@/features/accounts/model/research-context";
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
  searchParams,
}: PageProps<"/accounts/[accountId]/contacts/[contactId]">) {
  const { accountId, contactId } = await params;
  const context = researchContextQuery(await searchParams);
  const [account, contact] = await Promise.all([
    getAccountDetails(accountId, undefined, context),
    getAccountContact(accountId, contactId, undefined, context),
  ]);

  if (!account || !contact) notFound();

  return <ResearchNavigationProvider accountId={accountId} context={context}><ContactFullScreen account={account} contact={contact} /></ResearchNavigationProvider>;
}
