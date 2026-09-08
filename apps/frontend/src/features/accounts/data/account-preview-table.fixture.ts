import type { Account } from "../model/account";
import { FIXTURE_RESEARCH_STATUS_LABELS } from "../model/research-status-labels";

const previewDefaults = {
  createdAt: "2026-07-31T07:00:00.000Z",
  overallFit: "High",
  fitScore: 75,
  revenueBand: "$1 - $10M",
  employeeBand: "100-200",
  industryLabels: [
    "Healthcare",
    "Medical practice",
  ] as Account["industryLabels"],
  locationCount: 10,
  locationsLabel: "United States",
  lastModifiedAt: "2026-08-22T18:45:00.000Z",
  owner: {
    id: "aakash-shrivastava",
    name: "Aakash Shrivastava",
  },
  researchIsRefreshing: false,
  socials: [] as Account["socials"],
  customFields: [
    {
      id: "recall-fit",
      label: "Recall fit",
      presentation: "badge",
      primary: true,
      value: "Medium",
    },
  ] as Account["customFields"],
} as const;

function previewAccount(
  id: string,
  name: string,
  logoPath: string,
  enriched = false,
): Account {
  return {
    ...previewDefaults,
    id,
    name,
    logoPath,
    primaryProjectId: null,
    projects: [],
    websiteUrl: "https://example.com",
    researchStatus: enriched ? "completed" : "in_progress",
    researchStatusLabel: enriched
      ? FIXTURE_RESEARCH_STATUS_LABELS.completed
      : FIXTURE_RESEARCH_STATUS_LABELS.in_progress,
  };
}

export const accountPreviewTableFixtures: Account[] = [
  previewAccount(
    "capital-digestive-care",
    "Capital Digestive Care, LLC",
    "/logos/contentful-figma.png",
  ),
  previewAccount(
    "openai",
    "Synergy Medical Group",
    "/logos/sanity-figma.png",
  ),
  previewAccount(
    "wilmington-health",
    "Wilmington Health, PLLC",
    "/logos/wikipedia-figma.png",
  ),
  previewAccount(
    "anterior-digestive-alpha",
    "anterior_digestive_alpha",
    "/logos/ada-figma.png",
  ),
  previewAccount(
    "gi-alliance-of-illinois",
    "GI Alliance of Illinois",
    "/logos/godaddy-figma.png",
  ),
  previewAccount(
    "sierra-neurosurgery-group",
    "SIERRA NEUROSURGERY GROUP",
    "/logos/slack-figma.png",
    true,
  ),
  previewAccount(
    "washington-gastroenterology",
    "Washington Gastroenterology, PLLC",
    "/logos/webflow-figma.png",
    true,
  ),
  previewAccount(
    "connecticut-gi-1",
    "Connecticut GI (CTG)",
    "/logos/canny-figma.png",
    true,
  ),
  previewAccount(
    "connecticut-gi-2",
    "Connecticut GI (CTG)",
    "/logos/canny-figma.png",
    true,
  ),
  previewAccount(
    "michigan-gastroenterology-institute",
    "Michigan Gastroenterology Institute, PC",
    "/logos/marvel-figma.png",
    true,
  ),
  previewAccount(
    "gastroenterology-health-partners",
    "Gastroenterology Health Partners",
    "/logos/slack-figma.png",
    true,
  ),
  previewAccount(
    "gastroenterology-associates-northern-virginia",
    "Gastroenterology Associates Of Northern Virginia",
    "/logos/slack-figma.png",
    true,
  ),
  previewAccount(
    "general-digestive-partners",
    "General Digestive Partners",
    "/logos/slack-figma.png",
    true,
  ),
];
