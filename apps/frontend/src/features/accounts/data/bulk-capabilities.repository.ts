import {
  AccountBulkCapabilitiesSchema,
  type AccountBulkCapabilities,
} from "../model/bulk-actions";
import { accountRecoveryFor } from "./accounts-read-result";
import { fetchRead } from "./frontend-api";
import { accountsFixtureMode } from "./repository-mode";

export const DISABLED_ACCOUNT_BULK_CAPABILITIES: AccountBulkCapabilities = {
  addToProject: { allowed: false, maxItems: 100 },
  addToChat: { allowed: false, maxItems: 100 },
  projects: [],
};

export async function getAccountBulkCapabilities(
  read: typeof fetchRead = fetchRead,
): Promise<AccountBulkCapabilities> {
  return AccountBulkCapabilitiesSchema.parse(
    await read("/accounts/bulk-capabilities"),
  );
}

/**
 * Bulk actions are optional page capabilities. If their authenticated read is
 * unavailable or its contract is invalid, fail closed by hiding selection and
 * actions; the primary Account read remains responsible for page recovery.
 * Unexpected programming errors are still rethrown for observability.
 *
 * Fixture mode has no backend to ask and no project to write to, so the actions
 * are closed there too — a fixture table never pretends an action would land.
 */
export async function readAccountBulkCapabilities(
  read: () => Promise<AccountBulkCapabilities> = getAccountBulkCapabilities,
): Promise<AccountBulkCapabilities> {
  if (accountsFixtureMode()) return DISABLED_ACCOUNT_BULK_CAPABILITIES;
  try {
    return await read();
  } catch (error) {
    if (accountRecoveryFor(error)) return DISABLED_ACCOUNT_BULK_CAPABILITIES;
    throw error;
  }
}
