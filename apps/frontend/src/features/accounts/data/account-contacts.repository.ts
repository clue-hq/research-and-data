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

export interface AccountContactsRepository {
  list(accountId: string): Promise<AccountContactSummary[]>;
  get(
    accountId: string,
    contactId: string,
  ): Promise<AccountContactDetail | null>;
}

export const fixtureAccountContactsRepository: AccountContactsRepository = {
  async list(accountId) {
    if (accountId !== "openai") return [];
    return AccountContactsResponseSchema.parse({
      data: openAiContactsFixture,
    }).data;
  },
  async get(accountId, contactId) {
    if (accountId !== "openai" || contactId !== deniseDresserFixture.id) {
      return null;
    }
    return AccountContactDetailResponseSchema.parse({
      data: deniseDresserFixture,
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
  const apiBaseUrl = process.env.CLUE_API_BASE_URL;
  return apiBaseUrl
    ? createHttpAccountContactsRepository(apiBaseUrl)
    : fixtureAccountContactsRepository;
}

export function getAccountContacts(accountId: string) {
  return repository().list(accountId);
}

export function getAccountContact(accountId: string, contactId: string) {
  return repository().get(accountId, contactId);
}
