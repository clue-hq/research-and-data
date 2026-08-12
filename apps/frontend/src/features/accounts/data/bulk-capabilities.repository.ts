import {
  AccountBulkCapabilitiesSchema,
  ContactBulkCapabilitiesSchema,
  type AccountBulkCapabilities,
  type ContactBulkCapabilities,
} from "../model/bulk-actions";
import { accountRecoveryFor } from "./accounts-read-result";
import { fetchRead } from "./frontend-api";

export const DISABLED_ACCOUNT_BULK_CAPABILITIES: AccountBulkCapabilities = {
  addToProject: { allowed: false, maxItems: 100 },
  projects: [],
};

export const DISABLED_CONTACT_BULK_CAPABILITIES: ContactBulkCapabilities = {
  lookupWorkEmails: { allowed: false, maxItems: 20 },
};

export async function getAccountBulkCapabilities(
  read: typeof fetchRead = fetchRead,
): Promise<AccountBulkCapabilities> {
  return AccountBulkCapabilitiesSchema.parse(
    await read("/accounts/bulk-capabilities"),
  );
}

export async function getContactBulkCapabilities(
  accountId: string,
  read: typeof fetchRead = fetchRead,
): Promise<ContactBulkCapabilities> {
  return ContactBulkCapabilitiesSchema.parse(
    await read(
      `/accounts/${encodeURIComponent(accountId)}/contacts/bulk-capabilities`,
    ),
  );
}

/**
 * Bulk actions are optional page capabilities. If their authenticated read is
 * unavailable or its contract is invalid, fail closed by hiding selection and
 * actions; the primary Account read remains responsible for page recovery.
 * Unexpected programming errors are still rethrown for observability.
 */
export async function readAccountBulkCapabilities(
  read: () => Promise<AccountBulkCapabilities> = getAccountBulkCapabilities,
): Promise<AccountBulkCapabilities> {
  try {
    return await read();
  } catch (error) {
    if (accountRecoveryFor(error)) return DISABLED_ACCOUNT_BULK_CAPABILITIES;
    throw error;
  }
}

export async function readContactBulkCapabilities(
  accountId: string,
  read: (accountId: string) => Promise<ContactBulkCapabilities> =
    getContactBulkCapabilities,
): Promise<ContactBulkCapabilities> {
  try {
    return await read(accountId);
  } catch (error) {
    if (accountRecoveryFor(error)) return DISABLED_CONTACT_BULK_CAPABILITIES;
    throw error;
  }
}
