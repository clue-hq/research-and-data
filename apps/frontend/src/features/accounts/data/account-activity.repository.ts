import {
  AccountActivitySchema,
  type AccountActivity,
} from "../model/account-activity";
import { fetchRead } from "./frontend-api";

export interface AccountActivityRepository {
  get(accountId: string): Promise<AccountActivity | null>;
}

/** The Activity tab always reads the authenticated, workspace-scoped durable projection. */
export function createHttpAccountActivityRepository(
  read: typeof fetchRead = fetchRead,
): AccountActivityRepository {
  return {
    async get(accountId) {
      const body = await read(
        `/accounts/${encodeURIComponent(accountId)}/activity`,
        { recordNotFoundAllowed: true },
      );
      return body === null ? null : AccountActivitySchema.parse(body);
    },
  };
}

export async function getAccountActivity(
  accountId: string,
): Promise<AccountActivity | null> {
  return createHttpAccountActivityRepository().get(accountId);
}
