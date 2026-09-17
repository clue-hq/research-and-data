import type { AccountDetail } from "../../model/account-detail";
import type { ResearchContactReference } from "../../model/research-display";
import { zafranResearchEvidence } from "./evidence";
import { buildZafranSpecContent, zafranAccountCore as core, zafranAccountCustom as custom } from "./spec-content";

const accountId = "zafran-security";
const websiteLinks = [...core.Website!.matchAll(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g)];
const socialLabels: Record<string, AccountDetail["socials"][number]["label"]> = { LinkedIn: "LinkedIn", X: "Twitter" };

function contactRef(
  contactId: string,
  name: string,
  title: string,
  persona: string,
  emailState: ResearchContactReference["emailState"] = "verified",
): ResearchContactReference {
  return {
    accountId,
    contactId,
    name,
    title,
    persona,
    emailState,
  };
}

const vari = contactRef(
  "vari-kaur",
  "Vari Kaur",
  "Head of Growth Marketing",
  "Champion",
);
const nick = contactRef(
  "nick-fisher",
  "Nick Fisher",
  "VP Marketing",
  "Economic buyer",
);
const sanaz = contactRef(
  "sanaz-yashar",
  "Sanaz Yashar",
  "Co-Founder & CEO",
  "Executive sponsor",
);
const tom = contactRef(
  "tom-anthony",
  "Tom Anthony",
  "SVP Global Sales",
  "Adjacent buyer",
);
const ben = contactRef(
  "ben-seri",
  "Ben Seri",
  "Co-Founder & CTO",
  "Technical evaluator",
  "not_requested",
);

const zafranSpecContent = buildZafranSpecContent({
  contacts: { ben, nick, sanaz, tom, vari },
  evidence: zafranResearchEvidence,
});
const whatZafranDoes = zafranSpecContent.overviewDisplay.sections.find(
  (section) => section.key === "what-they-do",
)!;

export const zafranAccountDetailFixture: AccountDetail = {
  id: accountId,
  name: core.Account!,
  previewTitle: core.Account!,
  logoPath: "/logos/zafran.svg",
  websiteUrl: websiteLinks[0]![2]!,
  websiteLabel: websiteLinks[0]![1]!,
  researchStatus: "completed",
  researchStatusLabel: core["Research status"],
  industryLabels: core.Industry!.split(" · "),
  headcountLabel: core.Headcount!,
  locationsLabel: core.HQ!,
  revenueLabel: core.Revenue!,
  foundedLabel: core.Founded!,
  fundingLabel: core.Funding!,
  fitScore: core["Fit score"] === "—" ? null : Number(core["Fit score"]),
  fitScoreLabel: core["Fit score"],
  createdAt: "2026-08-22T07:00:00.000Z",
  lastModifiedAt: "2026-09-02T18:45:00.000Z",
  socials: websiteLinks.slice(1).map((link) => ({
    id: link[1] === "X" ? "twitter" : link[1]!.toLowerCase(),
    label: socialLabels[link[1]!]!, url: link[2]!,
  })),
  customFields: Object.entries(custom).map(([label, value], index) => ({
    id: ["abm-platform", "open-gtm-roles", "longest-marketing-req", "ats", "marketing-system"][index] ?? label.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
    label, value, presentation: "badge" as const, primary: index < 2,
  })),
  overallFit: core["Overall buying fit"] as AccountDetail["overallFit"],
  summaryParagraphs: [whatZafranDoes.intro?.[0]?.text ?? ""],
  businessParagraphs: [whatZafranDoes.intro?.[1]?.text ?? ""],
  fitCriteria: [],
  contacts: [
    {
      id: vari.contactId,
      name: vari.name,
      title: vari.title,
      persona: vari.persona,
      emailVerified: true,
      hasDetail: true,
    },
    {
      id: nick.contactId,
      name: nick.name,
      title: nick.title,
      persona: nick.persona,
      emailVerified: true,
      hasDetail: true,
    },
    {
      id: sanaz.contactId,
      name: sanaz.name,
      title: sanaz.title,
      persona: sanaz.persona,
      emailVerified: true,
      hasDetail: true,
    },
    {
      id: tom.contactId,
      name: tom.name,
      title: tom.title,
      persona: tom.persona,
      emailVerified: true,
      hasDetail: true,
    },
    {
      id: ben.contactId,
      name: ben.name,
      title: ben.title,
      persona: ben.persona,
      emailVerified: false,
      hasDetail: true,
    },
  ],
  insights: [
    {
      id: "abm-seat",
      source: "link",
      title: "ABM owner role remains open after 77 days",
      dateLabel: "2 Sep 2026",
      url: "https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf",
    },
    {
      id: "alliances",
      source: "link",
      title: "A new partner channel is being built from zero",
      dateLabel: "1 Sep 2026",
      url: "https://jobs.ashbyhq.com/zafran-security/b7b67d8b-b559-4cb8-bc1c-080f268c4c17",
    },
    {
      id: "gtm-hiring",
      source: "link",
      title: "Fourteen of 27 open roles are in go-to-market",
      dateLabel: "2 Sep 2026",
      url: "https://jobs.ashbyhq.com/zafran-security",
    },
  ],
  activity: [
    {
      id: "committee-confirmed",
      kind: "contacts",
      text: "Committee confirmed",
      actor: { type: "clue" },
      action: "confirmed the buying committee",
      timeLabel: "2 Sep 2026",
    },
    {
      id: "account-researched",
      kind: "summary",
      text: "Account researched",
      actor: { type: "clue" },
      action: "researched the account",
      timeLabel: "2 Sep 2026",
    },
    {
      id: "person-research",
      kind: "created",
      text: "Person research",
      actor: { type: "clue" },
      action: "researched contacts",
      timeLabel: "1 Sep 2026",
    },
  ],
  headerMetadata: [
    "zafran.io",
    "Cybersecurity",
    "Series C",
    "New York",
    "Overall fit: High",
    "Researched 2 Sep 2026",
  ],
  researchEvidence: zafranSpecContent.evidence,
  overviewDisplay: zafranSpecContent.overviewDisplay,
  buyingCommittee: zafranSpecContent.buyingCommittee,
};

export const zafranContactReferences = { ben, nick, sanaz, tom, vari };
