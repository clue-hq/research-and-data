import type { AccountDetail } from "../model/account-detail";
import { accountProjectFixtures } from "./account-projects.fixture";

const revenueCampaign = accountProjectFixtures.revenueCampaign;
const conference2026 = accountProjectFixtures.conference2026;

/**
 * The account detail as the read layer serves it.
 *
 * Note what is absent, deliberately: no `summaryParagraphs` / `businessParagraphs`
 * (D-10 — prose waits for a real synthesis step), no `fitCriteria`, no
 * `previewTitle`, no display labels, and no research status (that is an
 * `(account, project)` fact served on the list row).
 *
 * `neutralFacts` carries `core.*` fields and a pack field side by side, which
 * is the whole point of the D-7 resolution: an industry pack's custom fields
 * arrive through the same registry-driven list and render generically off
 * `fieldKey`, with no schema or adapter change.
 */
export const openAiAccountDetailFixture: AccountDetail = {
  id: "openai",
  name: "OpenAI",
  domain: "openai.com",
  aliases: ["OpenAI, L.L.C.", "OpenAI OpCo"],
  registryIds: { crunchbase: "openai", linkedin: "openai" },
  hqGeo: { city: "San Francisco", country: "US", region: "CA" },
  redirectedFrom: null,
  neutralFacts: [
    {
      fieldKey: "core.employee_count",
      value: 3200,
      freshness: "fresh",
      observedAt: "2026-08-01T12:00:00Z",
      provider: "clearbit",
    },
    {
      fieldKey: "core.revenue_band",
      value: "1b_plus",
      freshness: "fresh",
      observedAt: "2026-07-30T09:00:00Z",
      provider: "clearbit",
    },
    {
      fieldKey: "core.industry",
      value: "Artificial intelligence",
      freshness: "stale",
      observedAt: "2026-04-11T09:00:00Z",
      provider: "sumble",
    },
    {
      fieldKey: "core.tech_stack",
      value: ["Kubernetes", "Snowflake", "Salesforce"],
      freshness: "fresh",
      observedAt: "2026-07-22T16:30:00Z",
      provider: "sumble",
    },
    {
      // An industry-pack field: registered, not enumerated by the frontend.
      fieldKey: "saas_platform.seat_expansion_motion",
      value: { motion: "product_led", evidence_strength: "medium" },
      freshness: "fresh",
      observedAt: "2026-07-25T08:00:00Z",
      provider: "deep_research",
    },
  ],
  projectSections: [
    {
      projectId: revenueCampaign.projectId,
      name: revenueCampaign.name,
      addedVia: revenueCampaign.addedVia,
      addedAt: revenueCampaign.addedAt,
      scores: [
        {
          fit: 0.81,
          intent: 0.4,
          icpKey: "enterprise-ai",
          icpVersion: 2,
          scoredAt: "2026-08-01T12:00:00Z",
        },
      ],
      narratives: [
        {
          fieldKey: "account.value_narrative",
          value: {
            persona: "economic_buyer",
            angle_label: "consolidated account intelligence",
            argument:
              "OpenAI's enterprise organisation coordinates a large buying committee per opportunity; a consolidated, sourced account record shortens the internal hand-offs that slow those deals.",
          },
          observedAt: "2026-08-01T12:05:00Z",
          provider: "narrative_synthesis",
        },
        {
          fieldKey: "account.value_narrative",
          value: {
            persona: "champion",
            angle_label: "research leverage",
            argument:
              "A sourced buying-committee map removes the manual prospect research the team already automates internally.",
          },
          observedAt: "2026-08-01T12:05:00Z",
          provider: "narrative_synthesis",
        },
      ],
      insights: [
        {
          fieldKey: "account.signal.hiring",
          value:
            "Hiring across Sales, Strategic Pursuits, GTM Intelligence and regional business development.",
          observedAt: "2026-07-28T10:00:00Z",
          provider: "deep_research",
        },
        {
          fieldKey: "account.signal.leadership_change",
          value: {
            role: "Chief Revenue Officer",
            person: "Denise Dresser",
            announced_at: "2025-12-09",
          },
          observedAt: "2026-07-20T10:00:00Z",
          provider: "exa_deep",
        },
      ],
    },
    {
      projectId: conference2026.projectId,
      name: conference2026.name,
      addedVia: conference2026.addedVia,
      addedAt: conference2026.addedAt,
      // Targeted, nothing produced yet — a real state, served as an empty section.
      scores: [],
      narratives: [],
      insights: [],
    },
    {
      // The unattributed bucket: claims whose run maps to no project. Always last.
      projectId: null,
      name: null,
      addedVia: null,
      addedAt: null,
      scores: [
        {
          fit: 0.6,
          intent: null,
          icpKey: "manual-import",
          icpVersion: 1,
          scoredAt: "2026-06-02T08:00:00Z",
        },
      ],
      narratives: [],
      insights: [
        {
          fieldKey: "account.signal.press",
          value: "Enterprise reported as more than 40% of revenue.",
          observedAt: "2026-06-01T08:00:00Z",
          provider: "crm_import",
        },
      ],
    },
  ],
  committee: [
    {
      contactId: "denise-dresser",
      name: "Denise Dresser",
      persona: "economic_buyer",
      roleOnCommittee: "economic_buyer",
      projectIds: [revenueCampaign.projectId, conference2026.projectId],
    },
    {
      contactId: "brad-lightcap",
      name: "Brad Lightcap",
      persona: "champion",
      roleOnCommittee: "champion",
      projectIds: [revenueCampaign.projectId],
    },
    {
      contactId: "jakub-pachocki",
      name: "Jakub Pachocki",
      persona: "technical_evaluator",
      roleOnCommittee: "technical_evaluator",
      projectIds: [revenueCampaign.projectId],
    },
  ],
  coverage: {
    researchedFieldCount: 18,
    unresolvedFieldKeys: ["core.annual_revenue", "account.tooling.crm"],
  },
};
