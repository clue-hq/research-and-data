import type {
  AccountContactDetail,
  AccountContactSummary,
  ContactPersonaTone,
  ContactSocial,
} from "../model/account-contact";

function contact(
  id: string,
  name: string,
  title: string,
  persona: string,
  personaTone: ContactPersonaTone,
  influence: "High" | "Medium" | "Low",
  avatarUrl: string,
  emailStatus: "available" | "lookup",
  socials: ContactSocial[],
  profileAction: "none" | "preview" | "page" = "none",
): AccountContactSummary {
  return {
    id,
    name,
    title,
    persona,
    personaTone,
    influence,
    avatarUrl,
    emailStatus,
    socials,
    profileAction,
  };
}

export const openAiContactsFixture: AccountContactSummary[] = [
  contact("sam-altman", "Sam Altman", "CEO and Co-founder", "Executive Sponsor", "olive", "High", "/avatars/sam-altman.png", "available", ["linkedin", "x", "facebook", "instagram", "whatsapp"]),
  contact("fidji-simo", "Fidji Simo", "CEO of Applications", "Decision Maker", "orange", "High", "/avatars/fidji-simo.png", "lookup", ["linkedin", "x"]),
  contact("brad-lightcap", "Brad Lightcap", "Chief Operating Officer", "Decision Maker", "blue", "High", "/avatars/brad-lightcap.png", "available", ["linkedin", "x", "whatsapp"]),
  contact("denise-dresser", "Denise Dresser", "Chief Revenue Officer", "Economic Buyer", "orange", "High", "/avatars/denise-dresser.png", "lookup", ["linkedin", "x", "facebook", "instagram", "whatsapp"], "preview"),
  contact("sarah-friar", "Sarah Friar", "Chief Financial Officer", "Financial Buyer", "blue", "High", "/avatars/sarah-friar.png", "lookup", ["linkedin", "x", "facebook", "instagram", "whatsapp"]),
  contact("kevin-weil", "Kevin Weil", "Chief Product Officer", "Product Champion", "cyan", "High", "/avatars/kevin-weil.png", "available", ["linkedin", "x", "facebook", "instagram", "whatsapp"]),
  contact("mark-chen", "Mark Chen", "Chief Research Officer", "Technical Champion", "green", "High", "/avatars/mark-chen.png", "lookup", ["linkedin", "x", "facebook", "instagram", "whatsapp"]),
  contact("jakub-pachocki", "Jakub Pachocki", "Chief Scientist", "Technical Buyer", "pink", "High", "/avatars/jakub-pachocki.png", "available", ["linkedin", "x", "facebook", "instagram", "whatsapp"]),
  contact("arvind-kc", "Arvind KC", "Chief People Officer", "Operational Leader", "blue", "Medium", "/avatars/arvind-kc.png", "available", ["linkedin", "x", "facebook", "instagram", "whatsapp"]),
  contact("vijaye-raji", "Vijaye Raji", "CTO of Applications", "Technical Buyer", "olive", "High", "/avatars/vijaye-raji.png", "available", ["linkedin", "x", "facebook", "instagram", "whatsapp"]),
  contact("jason-kwon", "Jason Kwon", "Chief Strategy Officer", "Strategic Influencer", "blue", "High", "/avatars/jason-kwon.png", "available", ["linkedin", "x", "facebook", "instagram", "whatsapp"]),
  contact("ronnie-chatterji", "Aaron “Ronnie” Chatterji", "Chief Economist", "Strategic Influencer", "red", "Medium", "/avatars/ronnie-chatterji.png", "lookup", ["linkedin", "x", "facebook", "instagram", "whatsapp"]),
  contact("chris-lehane", "Chris Lehane", "Chief Global Affairs Officer", "External Stakeholder", "olive", "Medium", "/avatars/chris-lehane.png", "lookup", ["linkedin", "x", "facebook", "instagram", "whatsapp"]),
  contact("greg-brockman", "Greg Brockman", "President and Co-founder", "Executive Sponsor", "cyan", "High", "/avatars/greg-brockman.png", "lookup", ["linkedin", "x", "facebook", "instagram", "whatsapp"]),
];

const deniseSummary = openAiContactsFixture.find(
  (item) => item.id === "denise-dresser",
)!;

export const deniseDresserFixture: AccountContactDetail = {
  ...deniseSummary,
  accountId: "openai",
  accountName: "OpenAI",
  accountLogoPath: "/logos/openai-detail.svg",
  recentSignalsLabel: "5 in the last 180 days",
  linkedinLabel: "linkedin.com/in/denise",
  linkedinUrl: "https://www.linkedin.com/in/denise-dresser/",
  xLabel: "x.com/in/denise",
  xUrl: "https://x.com/",
  overviewParagraphs: [
    "Denise Dresser is OpenAI’s Chief Revenue Officer, responsible for the company’s global revenue strategy across enterprise and customer success.",
    "Before joining OpenAI, she served as CEO of Slack and led the company through its integration with Salesforce. Earlier in her career, she spent more than a decade at Salesforce building and leading global sales organizations that served some of the company’s largest and most complex customers.",
    "At OpenAI, her mandate is to help more organizations move from isolated AI experiments to dependable, company-wide deployment. Her responsibilities make her a highly relevant executive stakeholder for platforms that improve enterprise account prioritization, customer intelligence, and coordinated go-to-market execution.",
  ],
  reports: [],
  // No work-email claim behind this row: the chip cites nothing (ruling R5).
  emailClaimId: null,
  lastModifiedAt: "2026-04-08T00:00:00.000Z",
  customFields: [],
  researchEvidence: [],
  evidence: [
    {
      id: "cro-appointment",
      source: "link",
      title: "Appointed Chief Revenue Officer at OpenAI",
      dateLabel: "December 9, 2025",
      url: "https://openai.com/",
    },
    {
      id: "million-customers",
      source: "link",
      title: "OpenAI surpassed one million business customers",
      dateLabel: "November 5, 2025",
      url: "https://openai.com/",
    },
    {
      id: "enterprise-revenue",
      source: "linkedin",
      title: "Enterprise became more than 40% of OpenAI revenue",
      dateLabel: "April 8, 2026",
      url: "https://www.linkedin.com/company/openai/",
    },
  ],
};
