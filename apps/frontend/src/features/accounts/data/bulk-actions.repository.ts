import {
  BulkActionResponseSchema,
  type BulkActionResponse,
} from "../model/bulk-actions";
import { fetchMutation } from "./frontend-mutation";

export async function addAccountsToProject({
  accountIds,
  idempotencyKey,
  projectId,
}: {
  accountIds: string[];
  idempotencyKey: string;
  projectId: string;
}): Promise<BulkActionResponse> {
  return BulkActionResponseSchema.parse(
    await fetchMutation("/accounts/bulk-actions/add-to-project", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ accountIds, projectId }),
    }),
  );
}

export async function lookupContactEmails({
  accountId,
  contactIds,
  idempotencyKey,
}: {
  accountId: string;
  contactIds: string[];
  idempotencyKey: string;
}): Promise<BulkActionResponse> {
  return BulkActionResponseSchema.parse(
    await fetchMutation(
      `/accounts/${encodeURIComponent(accountId)}/contacts/bulk-actions/email-lookup`,
      {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({ contactIds }),
      },
    ),
  );
}
