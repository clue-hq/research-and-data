import type { AccountDetail } from "../model/account-detail";

export const openAiAccountDetailFixture: AccountDetail = {
  id: "openai",
  name: "OpenAI",
  previewTitle: "OpenAI",
  logoPath: "/logos/openai-detail.svg",
  websiteUrl: "https://openai.com",
  websiteLabel: "www.openai.com",
  researchStatus: "completed",
  researchStatusLabel: "Researched",
  owner: {
    id: "aakash-shrivastava",
    name: "Aakash Shrivastava",
  },
  industryLabels: [
    "Artificial intelligence",
    "Enterprise software",
    "Developer tools",
  ],
  headcountLabel: "5,000+",
  locationsLabel: "Global",
  revenueLabel: "Private / not disclosed",
  fitScore: 75,
  createdAt: "2026-07-31T07:00:00.000Z",
  lastModifiedAt: "2026-08-22T18:45:00.000Z",
  socials: [
    {
      id: "linkedin",
      label: "LinkedIn",
      url: "https://www.linkedin.com/company/openai/",
    },
    {
      id: "twitter",
      label: "Twitter",
      url: "https://x.com/OpenAI",
    },
    {
      id: "facebook",
      label: "Facebook",
      url: "https://www.facebook.com/openai/",
    },
    {
      id: "instagram",
      label: "Instagram",
      url: "https://www.instagram.com/openai/",
    },
  ],
  customFields: [
    {
      id: "recall-fit",
      label: "Recall fit",
      value: "Medium",
      presentation: "badge",
      primary: true,
    },
  ],
  overallFit: "High",
  summaryParagraphs: [
    "OpenAI is scaling from a frontier AI research organization into a global consumer, developer, and enterprise platform. Its commercial organization now supports more than one million business customers across ChatGPT for Work and direct API consumption.",
    "The company is investing in enterprise sales, strategic partnerships, customer success, GTM intelligence, support delivery, and product-led adoption. This creates a strong use case for Clue as a system that consolidates account signals, maps buying committees, and produces standardized research for complex enterprise opportunities.",
  ],
  businessParagraphs: [
    "OpenAI develops and deploys advanced AI systems through consumer products, workplace applications, developer APIs, coding agents, and enterprise infrastructure.",
    "Its enterprise strategy focuses on helping organizations move beyond isolated AI pilots toward company-wide deployment. OpenAI is building products that connect AI agents with internal tools, organizational knowledge, permissions, and business workflows.",
  ],
  fitCriteria: [
    {
      id: "enterprise-growth",
      matched: true,
      title: "Operates a large and rapidly growing enterprise business",
      evidence:
        "OpenAI reported more than one million paying business customers and more than seven million ChatGPT for Work seats in November 2025.",
    },
    {
      id: "global-gtm",
      matched: true,
      title: "Has a complex, global go-to-market organization",
      evidence:
        "The company is hiring across Sales, Strategic Pursuits, GTM Intelligence, AI Success, Support Delivery, Partnerships, and regional business development.",
    },
    {
      id: "research-workflow",
      matched: true,
      title: "Account research is directly relevant to its sales workflow",
      evidence:
        "OpenAI has publicly described an internal sales agent that researches inbound prospects, scores them against a rubric, sends personalized outreach, and updates the CRM.",
    },
    {
      id: "stakeholders",
      matched: true,
      title: "Requires multi-stakeholder account coordination",
      evidence:
        "OpenAI appointed Denise Dresser as Chief Revenue Officer to oversee global revenue strategy across enterprise and customer success.",
    },
    {
      id: "stack-undisclosed",
      matched: false,
      title: "Existing account-intelligence stack is not publicly disclosed",
      evidence:
        "The specific vendors and internal systems OpenAI currently uses for account intelligence are not publicly identified.",
    },
  ],
  contacts: [
    {
      id: "denise-dresser",
      name: "Denise Dresser",
      avatarUrl: "/avatars/denise-dresser.png",
      hasDetail: true,
    },
    {
      id: "brad-lightcap",
      name: "Brad Lightcap",
      avatarUrl: "/avatars/brad-lightcap.png",
      hasDetail: false,
    },
    {
      id: "sarah-friar",
      name: "Sarah Friar",
      avatarUrl: "/avatars/sarah-friar.png",
      hasDetail: false,
    },
  ],
  insights: [
    {
      id: "enterprise-revenue",
      source: "link",
      title: "OpenAI says enterprise now represents more than 40% of revenue",
      dateLabel: "April 8, 2026",
      url: "https://openai.com/",
    },
    {
      id: "cro",
      source: "link",
      title: "OpenAI appoints Denise Dresser as Chief Revenue Officer",
      dateLabel: "December 9, 2025",
      url: "https://openai.com/",
    },
    {
      id: "sales-agent",
      source: "linkedin",
      title:
        "OpenAI describes an internal agent for prospect research and qualification",
      dateLabel: "November 5, 2025",
      url: "https://www.linkedin.com/company/openai/",
    },
    {
      id: "gtm-intelligence",
      source: "x",
      title:
        "OpenAI is hiring a GTM Intelligence and Technical Success data leader",
      dateLabel: "Current opening",
      url: "https://x.com/OpenAI",
    },
  ],
  activity: [
    {
      id: "contacts-added",
      kind: "contacts",
      text: "Clue added 14 new contacts",
      timeLabel: "1 hour ago",
    },
    {
      id: "summary-updated",
      kind: "summary",
      text: "Clue updated Accounts summary",
      timeLabel: "1 hour ago",
    },
    {
      id: "account-created",
      kind: "created",
      text: "Clue created account OpenAI",
      timeLabel: "1 hour ago",
    },
  ],
  headerMetadata: [],
  researchEvidence: [],
  buyingCommittee: [],
};
