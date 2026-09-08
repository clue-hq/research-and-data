import type { AccountWorkspace } from "../model/account-workspace";

export const openAiWorkspaceFixture: AccountWorkspace = {
  accountId: "openai",
  insightSummary: [],
  researchEvidence: [],
  insights: [
    {
      id: "linkedin-launch",
      source: "linkedin",
      title:
        "Denise Dresser on LinkedIn: Building a new era of enterprise AI adoption",
      sourceLabel: "www.linkedin.com/company/openai/posts/enterprise-ai",
      url: "https://www.linkedin.com/company/openai/",
      summary:
        "OpenAI is expanding the operating model around enterprise deployment, customer success, and repeatable adoption. This creates a buying-readiness signal for account intelligence that can coordinate complex stakeholder groups.",
    },
    {
      id: "enterprise-customers",
      source: "link",
      title: "OpenAI surpassed one million business customers",
      sourceLabel: "https://openai.com/index/enterprise-ai",
      url: "https://openai.com/",
      summary:
        "The scale of the installed business base suggests a growing need for standardized account research, territory prioritization, and consistent opportunity planning across regional teams.",
    },
    {
      id: "cro-appointment",
      source: "link",
      title: "Denise Dresser appointed Chief Revenue Officer",
      sourceLabel: "https://openai.com/index/leadership",
      url: "https://openai.com/",
      summary:
        "A centralized revenue mandate spanning enterprise sales and customer success raises the value of a shared account intelligence layer and clear buying-committee maps.",
    },
    {
      id: "gtm-hiring",
      source: "x",
      title: "OpenAI is hiring across GTM intelligence and technical success",
      sourceLabel: "www.x.com/OpenAI/status/gtm",
      url: "https://x.com/OpenAI",
      summary:
        "New data and technical-success roles indicate investment in measurable, coordinated go-to-market systems rather than ad hoc research workflows.",
    },
    {
      id: "internal-agent",
      source: "linkedin",
      title: "OpenAI describes its internal prospect research agent",
      sourceLabel: "www.linkedin.com/company/openai/posts/sales-agent",
      url: "https://www.linkedin.com/company/openai/",
      summary:
        "The internal workflow researches prospects, scores them against a rubric, creates outreach, and updates CRM records—strong evidence that this category is operationally important.",
    },
  ],
  artifacts: [
    {
      id: "finance-review",
      title: "10x revenue ad",
      type: "ad",
      accountId: "openai",
      thumbnailPath: "/artifacts/finance-review.png",
      lastEditedLabel: "Last edited today",
    },
    {
      id: "insight-report",
      title: "print ad",
      type: "ad",
      accountId: "openai",
      thumbnailPath: "/artifacts/insight-report.png",
      lastEditedLabel: "Last edited today",
    },
    {
      id: "campaign-builder",
      title: "landing page builder",
      type: "web",
      accountId: "openai",
      thumbnailPath: "/artifacts/campaign-builder.png",
      lastEditedLabel: "Last edited today",
    },
  ],
  activity: [
    {
      id: "contacts-added",
      kind: "contacts",
      actor: { type: "clue" },
      text: "Clue added 14 new contacts",
      action: "added 14 new contacts",
      timeLabel: "1 hour ago",
    },
    {
      id: "summary-updated",
      kind: "summary",
      actor: { type: "clue" },
      text: "Clue updated Accounts summary",
      action: "updated Accounts summary",
      timeLabel: "1 hour ago",
    },
    {
      id: "account-created",
      kind: "created",
      actor: { type: "clue" },
      text: "Clue created account OpenAI",
      action: "created account OpenAI",
      timeLabel: "1 hour ago",
    },
  ],
};
