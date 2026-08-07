import type { Account } from "../model/account";

const previewDefaults = {
  overallFit: "High",
  fitScore: 75,
  revenueBand: "$1 - $10M",
  employeeBand: "100-200",
  locationCount: 10,
  researchIsRefreshing: false,
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
    researchStatus: enriched ? "fully_enriched" : "in_progress",
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
