import { ResearchNavigationProvider } from "@/features/accounts/components/research-link";
import { researchContextQuery } from "@/features/accounts/model/research-context";
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
  searchParams,
}: PageProps<"/accounts/[accountId]/contacts">) {
  const { accountId } = await params;
  const context = researchContextQuery(await searchParams);
  const [account, contacts] = await Promise.all([
    getAccountDetails(accountId, undefined, context),
    getAccountContacts(accountId, undefined, context),
  ]);
  // `contacts` is `null` only when the account itself is unknown (E4 answers
  // ACCOUNT_NOT_FOUND); an account with no committee is an empty list.
  if (!account || contacts === null) notFound();

  // No contact is "featured": the drawer opens on a row click and loads that
  // row's detail then (source map §6). The page used to scan the list for the
  // first previewable row and prefetch its whole detail payload.
  return <ResearchNavigationProvider accountId={accountId} context={context}><AccountContactsScreen account={account} contacts={contacts} /></ResearchNavigationProvider>;
}
