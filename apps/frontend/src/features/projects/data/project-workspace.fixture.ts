import type {
  ProjectHome,
  ProjectWorkspace,
} from "../model/project-workspace";

export const projectModels = [
  {
    description: "Clue's governed GPT-5.6 Terra conversation profile",
    id: "head-of-abm@v32",
    label: "GPT-5.6 Terra",
    shortLabel: "GPT-5.6 Terra",
  },
] as const;

export const projectHomeFixture: ProjectHome = {
  brands: [{ id: "brand-clue-demo", name: "Clue Demo Brand" }],
  composerCapabilities: {
    agentProfileSelection: true,
    attachments: true,
    contextRefs: true,
  },
  defaultAgentProfileId: "head-of-abm@v32",
  defaultBrandId: "brand-clue-demo",
  entities: [
    {
      id: "openai",
      imagePath: "/logos/openai.svg",
      label: "OpenAI",
      secondaryLabel: "www.openai.com",
      type: "account",
    },
    {
      id: "anthropic",
      imagePath: "/logos/anthropic.svg",
      label: "Anthropic",
      secondaryLabel: "www.anthropic.com",
      type: "account",
    },
    {
      id: "mistral-ai",
      imagePath: "/logos/mistral.svg",
      label: "Mistral AI",
      secondaryLabel: "www.mistral.com",
      type: "account",
    },
    {
      id: "perplexity-ai",
      imagePath: "/logos/perplexity.svg",
      label: "Perplexity AI",
      secondaryLabel: "www.perplexity.com",
      type: "account",
    },
    {
      id: "cohere",
      imagePath: "/logos/cohere.svg",
      label: "Cohere",
      secondaryLabel: "www.cohere.com",
      type: "account",
    },
    {
      accountName: "OpenAI",
      id: "denise-dresser",
      imagePath: "/avatars/denise-dresser.png",
      label: "Denise Dresser",
      secondaryLabel: "Chief Revenue Officer",
      type: "contact",
    },
    {
      accountName: "OpenAI",
      id: "fidji-simo",
      imagePath: "/avatars/fidji-simo.png",
      label: "Fidji Simo",
      secondaryLabel: "fidji@openai.com",
      type: "contact",
    },
    {
      accountName: "OpenAI",
      id: "brad-langdon",
      imagePath: "/avatars/brad-lightcap.png",
      label: "Brad Langdon",
      secondaryLabel: "brad@openai.com",
      type: "contact",
    },
  ],
  models: [...projectModels],
  suggestions: [
    "Find and research new accounts we can target before this quarter endsbased on conversions",
    "Highlight critical data points and what they reveal about user behavior",
    "Outline actionable recommendations based on the report’s findings for strategic planning",
  ],
};

/**
 * Fixture mode implements the real project-shell shape too. Prototype artifact,
 * plan, questionnaire, phase, model, and context data cannot leak through this
 * repository and masquerade as server state.
 */
export const projectWorkspaceFixture: ProjectWorkspace = {
  archivedAt: null,
  artifacts: [],
  brandId: "brand-clue-demo",
  composerCapabilities: {
    agentProfileSelection: false,
    attachments: false,
    contextRefs: false,
  },
  createdAt: "2026-08-01T00:00:00Z",
  defaultAgentProfileId: null,
  description: "",
  entities: [],
  id: "10m-landing-page-campaign",
  models: [],
  pinned: false,
  productId: null,
  status: "active",
  title: "10m+ landing page campaign",
  updatedAt: "2026-08-18T12:00:00Z",
};
