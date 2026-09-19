import {
  BulkActionResponseSchema,
  addToProjectNotice,
  reflectAddToProject,
  type BulkActionResponse,
  type BulkProjectOption,
} from "../model/bulk-actions";
import type { AccountRow } from "../model/create-account";
import { ClueApiError } from "./clue-api-error";
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

export type AddToProjectOutcome =
  | { status: "added"; notice: string; rows: AccountRow[] }
  | { status: "session_expired" }
  | { status: "refused"; notice: string };

/**
 * The whole add-to-project action, in one place a test can drive.
 *
 * The screen controller only holds state: it hands the selection here and acts
 * on the outcome. Nothing about the result is guessed — the notice is built
 * from the server's counts and only the subjects the server accepted are
 * reflected onto the rows. An expired session is reported as its own outcome so
 * the caller (which owns `window`) redirects rather than printing a notice.
 */
export async function addSelectedAccountsToProject(
  {
    accountIds,
    idempotencyKey,
    project,
    rows,
  }: {
    accountIds: string[];
    idempotencyKey: string;
    // Only the id and the name are read (the id is posted, the pair is stamped
    // on the accepted rows), so a screen that already knows its project can
    // submit without a picker option.
    project: Pick<BulkProjectOption, "id" | "name">;
    rows: readonly AccountRow[];
  },
  submit: typeof addAccountsToProject = addAccountsToProject,
): Promise<AddToProjectOutcome> {
  try {
    const result = await submit({
      accountIds,
      idempotencyKey,
      projectId: project.id,
    });
    return {
      status: "added",
      notice: `${project.name}: ${addToProjectNotice(result.counts)}`,
      rows: reflectAddToProject(rows, project, result),
    };
  } catch (error) {
    if (error instanceof ClueApiError && error.status === 401) {
      return { status: "session_expired" };
    }
    return {
      status: "refused",
      notice:
        error instanceof ClueApiError && error.status === 403
          ? "You no longer have permission to add Accounts to this project."
          : "The Account action could not finish. Try again to safely resume it.",
    };
  }
}
