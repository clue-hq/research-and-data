import type { Account } from "../model/account";
import { accountProjectFixtures } from "./account-projects.fixture";

/**
 * Development rows for the accounts table, shaped exactly like the as-built
 * list wire: semantic values only, `logoUrl` null everywhere (no logo pipeline
 * exists yet), per-project `scores` and `researchStatus` arrays, and an
 * integer `employeeCount` rather than a display band.
 *
 * The set deliberately exercises the states a live workspace produces: an
 * account scored by two projects under different ICPs, a membership whose
 * project has no resolvable name, a `researchStatus` entry for a project the
 * account is no longer a member of, and a fully null-heavy row with no
 * memberships at all.
 */

const revenueCampaign = accountProjectFixtures.revenueCampaign;
const customReports = accountProjectFixtures.customReports;
const conference2026 = accountProjectFixtures.conference2026;

function score(
  projectId: string,
  fit: number | null,
  intent: number | null,
  icpKey: string,
  icpVersion = 1,
) {
  return {
    projectId,
    fit,
    intent,
    icpKey,
    icpVersion,
    scoredAt: "2026-08-01T12:00:00Z",
  };
}

export const accountFixtures: Account[] = [
  {
    id: "anthropic",
    name: "Anthropic",
    domain: "anthropic.com",
    employeeCount: 1100,
    revenueBand: "100m_500m",
    logoUrl: null,
    projects: [revenueCampaign],
    primaryProjectId: revenueCampaign.projectId,
    scores: [score(revenueCampaign.projectId, 0.78, 0.41, "enterprise-ai")],
    researchStatus: [
      { projectId: revenueCampaign.projectId, status: "in_progress" },
    ],
    updatedAt: "2026-08-03T08:12:00Z",
  },
  {
    id: "openai",
    name: "OpenAI",
    domain: "openai.com",
    employeeCount: 3200,
    revenueBand: "1b_plus",
    logoUrl: null,
    projects: [revenueCampaign, conference2026],
    primaryProjectId: revenueCampaign.projectId,
    // The same account scored by two projects, under different ICP versions.
    scores: [
      score(revenueCampaign.projectId, 0.81, 0.4, "enterprise-ai", 2),
      score(conference2026.projectId, 0.55, null, "event-outreach", 3),
    ],
    researchStatus: [
      { projectId: revenueCampaign.projectId, status: "needs_review" },
      { projectId: conference2026.projectId, status: "in_progress" },
      // Research was launched for a project that no longer targets this
      // account. The wire reports it rather than hiding it.
      { projectId: "retired-pilot", status: "suspended" },
    ],
    updatedAt: "2026-08-05T17:45:00Z",
  },
  {
    id: "cohere",
    name: "Cohere",
    domain: "cohere.com",
    employeeCount: 420,
    revenueBand: "50m_100m",
    logoUrl: null,
    projects: [revenueCampaign],
    primaryProjectId: revenueCampaign.projectId,
    scores: [score(revenueCampaign.projectId, 0.62, null, "enterprise-ai")],
    researchStatus: [
      { projectId: revenueCampaign.projectId, status: "in_progress" },
    ],
    updatedAt: "2026-08-02T10:30:00Z",
  },
  {
    id: "perplexity-ai",
    name: "Perplexity AI",
    domain: "perplexity.ai",
    employeeCount: 260,
    revenueBand: "10m_50m",
    logoUrl: null,
    projects: [customReports],
    primaryProjectId: customReports.projectId,
    scores: [score(customReports.projectId, 0.58, 0.22, "reporting")],
    researchStatus: [
      { projectId: customReports.projectId, status: "in_progress" },
    ],
    updatedAt: "2026-08-01T09:00:00Z",
  },
  {
    id: "mistral-ai",
    name: "Mistral AI",
    domain: "mistral.ai",
    employeeCount: 310,
    revenueBand: "10m_50m",
    logoUrl: null,
    projects: [customReports],
    primaryProjectId: customReports.projectId,
    // Scored for fit, never for intent: the missing half stays null.
    scores: [score(customReports.projectId, 0.49, null, "reporting")],
    researchStatus: [
      { projectId: customReports.projectId, status: "in_progress" },
    ],
    updatedAt: "2026-07-30T14:20:00Z",
  },
  {
    id: "hugging-face",
    name: "Hugging Face",
    domain: "huggingface.co",
    employeeCount: 340,
    revenueBand: "10m_50m",
    logoUrl: null,
    projects: [conference2026],
    primaryProjectId: conference2026.projectId,
    scores: [score(conference2026.projectId, 0.71, 0.33, "event-outreach")],
    researchStatus: [
      { projectId: conference2026.projectId, status: "completed" },
    ],
    updatedAt: "2026-08-04T11:10:00Z",
  },
  {
    id: "scale-ai",
    name: "Scale AI",
    domain: "scale.com",
    employeeCount: 900,
    revenueBand: "100m_500m",
    logoUrl: null,
    projects: [revenueCampaign],
    primaryProjectId: revenueCampaign.projectId,
    scores: [score(revenueCampaign.projectId, 0.66, 0.18, "enterprise-ai")],
    researchStatus: [
      { projectId: revenueCampaign.projectId, status: "completed" },
    ],
    updatedAt: "2026-08-04T15:35:00Z",
  },
  {
    id: "airtable",
    name: "Airtable",
    domain: "airtable.com",
    employeeCount: 1400,
    revenueBand: "100m_500m",
    logoUrl: null,
    // A second membership whose project has no resolvable name.
    projects: [conference2026, accountProjectFixtures.unnamed],
    primaryProjectId: conference2026.projectId,
    scores: [score(conference2026.projectId, 0.44, null, "event-outreach")],
    researchStatus: [
      { projectId: conference2026.projectId, status: "needs_review" },
    ],
    updatedAt: "2026-08-06T07:55:00Z",
  },
  {
    id: "snowflake",
    name: "Snowflake",
    domain: "snowflake.com",
    employeeCount: 7800,
    revenueBand: "1b_plus",
    logoUrl: null,
    projects: [conference2026],
    primaryProjectId: conference2026.projectId,
    scores: [score(conference2026.projectId, 0.69, 0.51, "event-outreach")],
    researchStatus: [
      { projectId: conference2026.projectId, status: "completed" },
    ],
    updatedAt: "2026-08-05T12:00:00Z",
  },
  {
    id: "antigravity",
    name: "Antigravity",
    domain: "antigravity.dev",
    employeeCount: 45,
    revenueBand: "under_1m",
    logoUrl: null,
    projects: [customReports],
    primaryProjectId: customReports.projectId,
    scores: [score(customReports.projectId, 0.35, null, "reporting")],
    researchStatus: [
      { projectId: customReports.projectId, status: "completed" },
    ],
    updatedAt: "2026-07-29T18:05:00Z",
  },
  {
    id: "google-deepmind",
    name: "Google DeepMind",
    domain: "deepmind.google",
    employeeCount: 2600,
    revenueBand: "1b_plus",
    logoUrl: null,
    projects: [revenueCampaign],
    primaryProjectId: revenueCampaign.projectId,
    scores: [score(revenueCampaign.projectId, 0.74, 0.29, "enterprise-ai")],
    researchStatus: [
      { projectId: revenueCampaign.projectId, status: "completed" },
    ],
    updatedAt: "2026-08-03T21:40:00Z",
  },
  {
    id: "midjourney",
    name: "Midjourney",
    domain: "midjourney.com",
    employeeCount: 60,
    revenueBand: "50m_100m",
    logoUrl: null,
    projects: [customReports],
    primaryProjectId: customReports.projectId,
    scores: [score(customReports.projectId, 0.4, null, "reporting")],
    researchStatus: [
      { projectId: customReports.projectId, status: "suspended" },
    ],
    updatedAt: "2026-07-31T13:15:00Z",
  },
  {
    id: "cursor",
    name: "Cursor",
    domain: "cursor.com",
    employeeCount: 120,
    revenueBand: "10m_50m",
    logoUrl: null,
    projects: [customReports, conference2026],
    primaryProjectId: customReports.projectId,
    scores: [
      score(customReports.projectId, 0.52, 0.61, "reporting"),
      score(conference2026.projectId, 0.47, null, "event-outreach"),
    ],
    researchStatus: [
      { projectId: customReports.projectId, status: "in_progress" },
      { projectId: conference2026.projectId, status: "not_started" },
    ],
    updatedAt: "2026-08-06T19:25:00Z",
  },
  {
    /**
     * A discovered account no project targets yet: no memberships, no scores,
     * no status, and no enrichment. Every enrichment cell renders its honest
     * absence rather than a placeholder.
     */
    id: "neuralink",
    name: "Neuralink",
    domain: null,
    employeeCount: null,
    revenueBand: null,
    logoUrl: null,
    projects: [],
    primaryProjectId: null,
    scores: [],
    researchStatus: [],
    updatedAt: "2026-08-07T06:00:00Z",
  },
];
