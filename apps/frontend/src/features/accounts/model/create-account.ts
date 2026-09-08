import type { Account, AccountOwner } from "./account";

/**
 * The optimistic row a just-created account shows until the server answers.
 *
 * Nothing here is invented about the account itself: an unscored account has no
 * band and no score (`null`, ruling R7 — never a zero score or a guessed band),
 * there is no logo pipeline (`null`, ruling S2), and the research status is the
 * one fact creation does establish. D4 Task 5 replaces this with the row the
 * POST returns.
 */
export function createLocalAccount(name: string, websiteUrl: string, creator: AccountOwner): Account {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
  return {
    employeeBand: "Unknown",
    fitScore: null,
    id: `${slug}-${crypto.randomUUID()}`,
    industryLabels: [],
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
