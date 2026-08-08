import {
  AccountContactDetailSchema,
  AccountContactsResponseSchema,
  type AccountContactDetail,
  type AccountContactSummary,
} from "../model/account-contact";
import {
  deniseDresserFixture,
  openAiContactsFixture,
} from "./account-contacts.fixture";
import { apiBaseUrl, fetchRead } from "./frontend-api";

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
      meta: { total: openAiContactsFixture.length },
    }).data;
  },
  async get(accountId, contactId) {
    if (accountId !== "openai" || contactId !== deniseDresserFixture.id) {
      return null;
    }
    return AccountContactDetailSchema.parse(deniseDresserFixture);
  },
};

/**
 * Both contact endpoints follow a merged account silently and serve the
 * survivor's committee. An empty committee is a `200` with an empty list, not a
 * `404` — the governed committee reads M8D research references whose production
 * writer is still behind the R1 quarantine, so live data is empty today and the
 * seam is proven by fixtures.
 */
export function createHttpAccountContactsRepository(): AccountContactsRepository {
  return {
    async list(accountId) {
      const body = await fetchRead(
        `/accounts/${encodeURIComponent(accountId)}/contacts`,
      );
      if (body === null) return [];
      return AccountContactsResponseSchema.parse(body).data;
    },
    async get(accountId, contactId) {
      const body = await fetchRead(
        `/accounts/${encodeURIComponent(accountId)}/contacts/${encodeURIComponent(contactId)}`,
      );
      // A single resource: the profile object itself, no `data` wrapper.
      return body === null ? null : AccountContactDetailSchema.parse(body);
    },
  };
}

function repository(): AccountContactsRepository {
  return apiBaseUrl()
    ? createHttpAccountContactsRepository()
    : fixtureAccountContactsRepository;
}

export function getAccountContacts(accountId: string) {
  return repository().list(accountId);
}

export function getAccountContact(accountId: string, contactId: string) {
  return repository().get(accountId, contactId);
}
