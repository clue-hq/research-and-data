import {
  ContactEmailLookupSchema,
  type ContactEmailLookup,
} from "../model/account-contact";
import { fetchMutation } from "./frontend-mutation";

export async function startContactEmailLookup(
  accountId: string,
  contactId: string,
): Promise<ContactEmailLookup> {
  const body = await fetchMutation(
    `/accounts/${encodeURIComponent(accountId)}/contacts/${encodeURIComponent(contactId)}/email-lookup`,
    { method: "POST", body: "{}" },
  );
  return ContactEmailLookupSchema.parse(body);
}

export async function pollContactEmailLookup(
  accountId: string,
  contactId: string,
  lookupId: string,
): Promise<ContactEmailLookup> {
  const body = await fetchMutation(
    `/accounts/${encodeURIComponent(accountId)}/contacts/${encodeURIComponent(contactId)}/email-lookup/${encodeURIComponent(lookupId)}/poll`,
    { method: "POST", body: "{}" },
  );
  return ContactEmailLookupSchema.parse(body);
}
