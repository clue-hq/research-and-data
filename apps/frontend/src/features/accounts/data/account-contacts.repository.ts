import { withResearchContext, type ResearchContextQuery } from "../model/research-context";
import {
  AccountContactDetailResponseSchema,
  AccountContactsResponseSchema,
  type AccountContactDetail,
  type AccountContactSummary,
} from "../model/account-contact";
import {
  deniseDresserFixture,
  openAiContactsFixture,
} from "./account-contacts.fixture";
import {
  zafranContactDetails,
  zafranContactsFixture,
} from "./zafran/contacts";
import { fetchRead } from "./frontend-api";
import { accountsFixtureMode } from "./repository-mode";

export interface AccountContactsRepository {
  /** `null` means "no such account" — an account with no committee is `[]`. */
  list(accountId: string, context?: ResearchContextQuery): Promise<AccountContactSummary[] | null>;
  get(
    accountId: string,
    contactId: string,
    context?: ResearchContextQuery,
  ): Promise<AccountContactDetail | null>;
}

export const fixtureAccountContactsRepository: AccountContactsRepository = {
  async list(accountId) {
    const contacts =
      accountId === "openai"
        ? openAiContactsFixture
        : accountId === "zafran-security"
          ? zafranContactsFixture
          : null;
    if (!contacts) return null;
    return AccountContactsResponseSchema.parse({
      data: contacts,
    }).data;
  },
  async get(accountId, contactId) {
    const contact =
      accountId === "openai" && contactId === deniseDresserFixture.id
        ? deniseDresserFixture
        : accountId === "zafran-security"
          ? zafranContactDetails[contactId]
          : null;
    if (!contact) return null;
    return AccountContactDetailResponseSchema.parse({
      data: contact,
    }).data;
  },
};

/**
 * The live contacts reads.
 *
 * E4 `GET /accounts/{id}/contacts` serves `{data, meta: {total}}`; the rows are
 * the whole committee, so `meta.total` is redundant here and is not read (the
 * schema is non-strict, so parsing the envelope with `{data}` is enough).
 * E5 `GET /accounts/{id}/contacts/{contactId}` serves `{data}`.
 */
export function createHttpAccountContactsRepository(
  read: typeof fetchRead = fetchRead,
): AccountContactsRepository {
  return {
    async list(accountId, context) {
      const body = await read(
        withResearchContext(`/accounts/${encodeURIComponent(accountId)}/contacts`, context),
        { recordNotFoundAllowed: true },
      );
      if (body === null) return null;
      return AccountContactsResponseSchema.parse(body).data;
    },
    async get(accountId, contactId, context) {
      const body = await read(
        withResearchContext(`/accounts/${encodeURIComponent(accountId)}/contacts/${encodeURIComponent(contactId)}`, context),
        { recordNotFoundAllowed: true },
      );
      if (body === null) return null;
      return AccountContactDetailResponseSchema.parse(body).data;
    },
  };
}

function repository(read: typeof fetchRead): AccountContactsRepository {
  return accountsFixtureMode()
    ? fixtureAccountContactsRepository
    : createHttpAccountContactsRepository(read);
}

export function getAccountContacts(
  accountId: string,
  read: typeof fetchRead = fetchRead,
  context?: ResearchContextQuery,
) {
  return repository(read).list(accountId, context);
}

export function getAccountContact(
  accountId: string,
  contactId: string,
  read: typeof fetchRead = fetchRead,
  context?: ResearchContextQuery,
) {
  return repository(read).get(accountId, contactId, context);
}
