import type { AccountProject } from "../model/account";

/**
 * Development-only project catalog shared with the account filter shell.
 * Backend project IDs and titles replace these records through the account
 * response and project repository.
 */
export const accountProjectFixtures = {
  revenueCampaign: {
    id: "10m-landing-page-campaign",
    name: "10x revenue campaign",
  },
  customReports: {
    id: "custom-reports",
    name: "custom reports",
  },
  conference2026: {
    id: "conference-2026",
    name: "conference 2026",
  },
} satisfies Record<string, AccountProject>;
