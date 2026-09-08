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
import { accountsFixtureMode } from "./repository-mode";

export interface AccountContactsRepository {
  list(accountId: string): Promise<AccountContactSummary[]>;
  get(
    accountId: string,
    contactId: string,
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
    if (!contacts) return [];
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

export function createHttpAccountContactsRepository(
  apiBaseUrl: string,
): AccountContactsRepository {
  const base = `${apiBaseUrl.replace(/\/$/, "")}/`;
  return {
    async list(accountId) {
      const url = new URL(
        `/api/v1/accounts/${encodeURIComponent(accountId)}/contacts`,
        base,
      );
      const response = await fetch(url, {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(`Account contacts API returned ${response.status}`);
      }
      return AccountContactsResponseSchema.parse(await response.json()).data;
    },
    async get(accountId, contactId) {
      const url = new URL(
        `/api/v1/accounts/${encodeURIComponent(accountId)}/contacts/${encodeURIComponent(contactId)}`,
        base,
      );
      const response = await fetch(url, {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (response.status === 404) return null;
      if (!response.ok) {
        throw new Error(`Contact details API returned ${response.status}`);
      }
      return AccountContactDetailResponseSchema.parse(await response.json())
        .data;
    },
  };
}

function repository(): AccountContactsRepository {
  return accountsFixtureMode()
    ? fixtureAccountContactsRepository
    : liveRepository();
}

export function getAccountContacts(accountId: string) {
  return repository().list(accountId);
}

export function getAccountContact(accountId: string, contactId: string) {
  return repository().get(accountId, contactId);
}

/**
 * The live adapter lands in D4 Task 4 (the amended read contract). Until then
 * the live path refuses loudly: it must never silently fall back to fixtures.
 */
function liveRepository(): never {
  throw new Error("accounts live adapter lands in D4 Task 4");
}
