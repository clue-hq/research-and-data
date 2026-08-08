import type { AccountProject } from "../model/account";

/**
 * Development-only project catalog shared with the account filter shell.
 *
 * Shapes match the wire's membership record: `projectId` (not `id`), the
 * read-layer-resolved `name`, and the `addedVia`/`addedAt` pair recording how
 * and when the project acquired the account. `addedVia` is an open channel
 * token, so the fixtures exercise more than one of them.
 */
export const accountProjectFixtures = {
  revenueCampaign: {
    projectId: "10m-landing-page-campaign",
    name: "10x revenue campaign",
    addedVia: "discovered",
    addedAt: "2026-07-02T09:15:00Z",
  },
  customReports: {
    projectId: "custom-reports",
    name: "custom reports",
    addedVia: "imported",
    addedAt: "2026-07-14T16:40:00Z",
  },
  conference2026: {
    projectId: "conference-2026",
    name: "conference 2026",
    addedVia: "directive",
    addedAt: "2026-07-28T11:05:00Z",
  },
  /**
   * A membership whose project this workspace holds no `project` row for. The
   * name is `null` and the id must never be rendered as a fallback label.
   */
  unnamed: {
    projectId: "prj-unnamed-lineage",
    name: null,
    addedVia: null,
    addedAt: null,
  },
} satisfies Record<string, AccountProject>;
