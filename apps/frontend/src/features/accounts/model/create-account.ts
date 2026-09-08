import type { Account, AccountOwner } from "./account";

/**
 * A locally created account that the backend has never seen.
 *
 * `isLocalDraft` is a UI-only marker and is deliberately NOT part of
 * `AccountSchema`: it never travels on the wire, and parsing a draft through
 * the model drops it. A row carrying it is one the browser invented, so the
 * table says "Not saved yet" and the bulk actions refuse to submit it.
 */
export type LocalDraftAccount = Account & { readonly isLocalDraft: true };

/** What the table renders: served accounts plus any local drafts above them. */
export type AccountRow = Account & { readonly isLocalDraft?: true };

export function isLocalDraftAccount(account: AccountRow): boolean {
  return account.isLocalDraft === true;
}

/**
 * The row a just-created account shows. It is not optimistic: nothing is
 * invented about the account (founder ruling f).
 *
 * An unscored account has no band and no score (`null`, ruling R7 — never a
 * zero score or a guessed band), there is no logo pipeline (`null`, ruling S2),
 * unknown bands say "Unknown", and the research status is the one fact creation
 * does establish. The account exists only in this browser tab until a backend
 * write endpoint exists; that endpoint is a recorded follow-up, not a stub.
 */
export function createLocalAccount(
  name: string,
  websiteUrl: string,
  creator: AccountOwner,
): LocalDraftAccount {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
  return {
    employeeBand: "Unknown",
    fitScore: null,
    id: `${slug}-${crypto.randomUUID()}`,
    industryLabels: [],
    isLocalDraft: true,
    locationCount: 0,
    logoPath: null,
    name,
    owner: { ...creator },
    createdBy: { ...creator },
    overallFit: null,
    primaryProjectId: null,
    projects: [],
    customFields: [],
    researchIsRefreshing: false,
    researchStatus: "not_started",
    researchStatusLabel: "Not started",
    revenueBand: "Unknown",
    socials: [],
    websiteUrl,
  };
}
