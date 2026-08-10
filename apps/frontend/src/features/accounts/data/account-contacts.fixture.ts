import type {
  AccountContactDetail,
  AccountContactSummary,
} from "../model/account-contact";
import type { Persona } from "../model/vocabulary";
import { accountProjectFixtures } from "./account-projects.fixture";

const revenueCampaign = accountProjectFixtures.revenueCampaign.projectId;
const conference2026 = accountProjectFixtures.conference2026.projectId;

/**
 * Development committee rows, shaped like the governed contacts wire.
 *
 * What is gone, and why: no `avatarUrl` (G1 — no avatar pipeline and the
 * browser does not scrape), no `influence` band (D-7 — `roleOnCommittee`
 * carries the real confidence), no non-LinkedIn socials (G2), no email address
 * (G3), and no evidence URLs (G4 — provenance chips only).
 *
 * `titleRestricted` is exercised on purpose: a weakly-bound contact's title is
 * served absent WITH the marker, which is a different answer from a title the
 * backend simply does not hold.
 */
function contact(
  id: string,
  name: string | null,
  title: string | null,
  persona: Persona,
  role: string,
  confidence: number | null,
  linkedinUrl: string | null,
  projectIds: string[],
  typeCount: number,
  titleRestricted = false,
): AccountContactSummary {
  return {
    id,
    name,
    title,
    titleRestricted,
    persona,
    roleOnCommittee: { value: role, confidence },
    linkedinUrl,
    projectIds,
    signals: { typeCount },
  };
}

export const openAiContactsFixture: AccountContactSummary[] = [
  contact(
    "denise-dresser",
    "Denise Dresser",
    "Chief Revenue Officer",
    "economic_buyer",
    "economic_buyer",
    0.87,
    "https://www.linkedin.com/in/denise-dresser/",
    [revenueCampaign, conference2026],
    2,
  ),
  contact(
    "brad-lightcap",
    "Brad Lightcap",
    "Chief Operating Officer",
    "champion",
    "champion",
    0.74,
    "https://www.linkedin.com/in/bradlightcap/",
    [revenueCampaign],
    1,
  ),
  contact(
    "sarah-friar",
    "Sarah Friar",
    "Chief Financial Officer",
    "economic_buyer",
    "economic_buyer",
    0.66,
    null,
    [revenueCampaign],
    0,
  ),
  contact(
    "jakub-pachocki",
    "Jakub Pachocki",
    "Chief Scientist",
    "technical_evaluator",
    "technical_evaluator",
    0.58,
    "https://www.linkedin.com/in/jakub-pachocki/",
    [revenueCampaign],
    1,
  ),
  contact(
    // Display governance withheld the title: absent, and marked as withheld.
    "unresolved-procurement-lead",
    "Procurement lead",
    null,
    "blocker",
    "blocker",
    0.31,
    null,
    [conference2026],
    0,
    true,
  ),
  contact(
    // No name resolved at all — absent and unmarked, which is the other answer.
    "unnamed-committee-member",
    null,
    "VP Platform Engineering",
    "technical_evaluator",
    "technical_evaluator",
    null,
    null,
    [conference2026],
    0,
  ),
];

const deniseSummary = openAiContactsFixture.find(
  (item) => item.id === "denise-dresser",
)!;

export const deniseDresserFixture: AccountContactDetail = {
  ...deniseSummary,
  accountId: "openai",
  accountName: "OpenAI",
  redirectedFrom: null,
  professionalFacts: [
    {
      fieldKey: "contact.title",
      value: "Chief Revenue Officer",
      observedAt: "2026-07-18T09:00:00Z",
      provider: "sumble",
      restricted: false,
    },
    {
      fieldKey: "contact.seniority",
      value: "c_level",
      observedAt: "2026-07-18T09:00:00Z",
      provider: "sumble",
      restricted: false,
    },
    {
      fieldKey: "contact.facet.recent_post",
      value:
        "Posted about moving enterprises from isolated AI pilots to company-wide deployment.",
      observedAt: "2026-07-26T14:30:00Z",
      provider: "exa_deep",
      restricted: false,
    },
    {
      // Withheld by policy: no value and no provenance, only the marker.
      fieldKey: "contact.facet.public_appearances",
      value: null,
      observedAt: null,
      provider: null,
      restricted: true,
    },
  ],
  evidence: [
    { provider: "sumble", observedAt: "2026-07-18T09:00:00Z" },
    { provider: "exa_deep", observedAt: "2026-07-26T14:30:00Z" },
    { provider: "committee_inference", observedAt: "2026-08-01T12:00:00Z" },
  ],
};
