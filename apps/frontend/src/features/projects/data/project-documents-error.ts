import { ClueApiError } from "@/features/accounts/data/clue-api-error";

export function projectDocumentError(status: number, code: string, requestId: string | null, editing = false): ClueApiError {
  let message = "Unable to load this document. Please try again.";
  if (editing) message = "Unable to save this document. Your changes are still here; please try again.";
  if (status === 401 || status === 403) {
    message = `You do not have permission to ${editing ? "edit" : "view"} this document.`;
  } else if (status === 409) {
    message = "A newer version of this document exists. Your changes are still here; copy them before loading the latest version.";
  } else if (status === 404) {
    message = "This document is no longer available in this project.";
  } else if (status === 422 && editing) {
    message = "This document could not be saved. Check that it is not empty and try again.";
  }
  return new ClueApiError(message, { status, code, requestId });
}
