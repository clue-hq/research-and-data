import type { Account, AccountOwner } from "./account";

export function createLocalAccount(name: string, websiteUrl: string, creator: AccountOwner): Account {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
  return {
    employeeBand: "Unknown",
    fitScore: 0,
    id: `${slug}-${crypto.randomUUID()}`,
    industryLabels: [],
    locationCount: 0,
    logoPath: "/icons/building.svg",
    name,
    owner: { ...creator },
    createdBy: { ...creator },
    overallFit: "Medium",
    primaryProjectId: null,
    projects: [],
    customFields: [],
    researchIsRefreshing: false,
    researchStatus: "not_started",
    revenueBand: "Unknown",
    socials: [],
    websiteUrl,
  };
}
