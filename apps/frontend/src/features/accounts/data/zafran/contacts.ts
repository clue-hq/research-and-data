import type {
  AccountContactDetail,
  AccountContactSummary,
  ContactPersonaTone,
} from "../../model/account-contact";
import { zafranContactReferences } from "./account";
import { zafranResearchEvidence } from "./evidence";
import { buildZafranSpecContent, fieldText, zafranNickCore as core } from "./spec-content";
import { formatTenure, researchCountLabel } from "../../model/research-presentation";
import type { ResearchDisplayBlock } from "../../model/research-display";

function contact(
  id: string,
  name: string,
  title: string,
  persona: string,
  personaTone: ContactPersonaTone,
  influence: "High" | "Medium" | "Low",
  emailStatus: "available" | "lookup",
  emailLabel?: string,
): AccountContactSummary {
  return {
    id,
    name,
    title,
    persona,
    personaTone,
    influence,
    emailStatus,
    emailLabel,
    socials: ["linkedin"],
    profileAction: "page",
  };
}

const { vari } = zafranContactReferences;

export const zafranContactsFixture: AccountContactSummary[] = [
  contact(
    "nick-fisher",
    "Nick Fisher",
    fieldText(core.Title!),
    "Economic Buyer",
    "orange",
    "High",
    "available",
    "nick@zafran.io",
  ),
  contact(
    "vari-kaur",
    "Vari Kaur",
    "Head of Growth Marketing",
    "Champion",
    "green",
    "High",
    "available",
    "vari@zafran.io",
  ),
  contact(
    "sanaz-yashar",
    "Sanaz Yashar",
    "Co-Founder & CEO",
    "Executive Sponsor",
    "olive",
    "High",
    "available",
    "sanaz@zafran.io",
  ),
  contact(
    "tom-anthony",
    "Tom Anthony",
    "SVP Global Sales",
    "Adjacent Buyer",
    "blue",
    "High",
    "available",
    "tom@zafran.io",
  ),
  contact(
    "ben-seri",
    "Ben Seri",
    "Co-Founder & CTO",
    "Technical Evaluator",
    "cyan",
    "Medium",
    "lookup",
  ),
];

const zafranSpecContent = buildZafranSpecContent({
  contacts: zafranContactReferences,
  evidence: zafranResearchEvidence,
});

const nickSummary = zafranContactsFixture[0]!;
const start = core["At Zafran since"]!.match(/^(\w+) (\d{4})/)!;
const employmentStartedAt = new Date(`${start[1]} 1, ${start[2]} UTC`).toISOString().slice(0, 10);
const locationLabel = fieldText(core.Location!.replace(/\s*\[[^\]]+]\([^)]+\)/g, ""));

export const nickFisherFixture: AccountContactDetail = {
  ...nickSummary,
  accountId: "zafran-security",
  accountName: "Zafran Security",
  accountLogoPath: "/logos/zafran.svg",
  recentSignalsLabel: researchCountLabel(zafranSpecContent.contactDisplay.sections),
  linkedinLabel: core.LinkedIn!.match(/\[([^\]]+)\]/)![1]!,
  linkedinUrl: core.LinkedIn!.match(/\]\(([^)]+)\)/)![1]!,
  emailLabel: fieldText(core.Email!),
  emailVerifiedAt: "2026-08-31",
  locationLabel,
  bestFirstChannelLabel: core["Best first channel"],
  educationLabel: fieldText(core.Education!),
  employmentStartedAt,
  tenureLabel: formatTenure(employmentStartedAt, new Date().toISOString().slice(0, 10)),
  linkedinFollowers: Number(core.LinkedIn!.match(/([\d,]+) followers/)![1]!.replace(/,/g, "")),
  linkedinCreator: core.LinkedIn!.includes("creator"),
  locationClaimId: "nick-location",
  reports: [vari],
  overviewParagraphs: zafranSpecContent.contactDisplay.sections[0]!.items[0]!.body.map((sentence) => sentence.text),
  evidence: [],
  researchEvidence: [...zafranSpecContent.evidence, {
    ...zafranResearchEvidence.find((record) => record.claimId === "ashby-bdr-role")!,
    claimId: "nick-location",
    quote: null,
    researchExcerpt: locationLabel,
  }],
  contactDisplay: zafranSpecContent.contactDisplay,
};

function compactDetail(
  summary: AccountContactSummary,
  linkedinUrl: string,
  emailLabel?: string,
): AccountContactDetail {
  const personItems = zafranSpecContent.insightsDisplay.sections
    .find((section) => section.key === "contact-insights")!.items
    .filter((item) => item.subject?.contactId === summary.id);
  const relatedSections = zafranSpecContent.insightsDisplay.sections
    .filter((section) => section.key !== "contact-insights" && !section.restricted)
    .map((section) => ({ ...section, items: section.items.filter((item) => item.contactRefs.some((ref) => ref.contactId === summary.id)) }))
    .filter((section) => section.items.length > 0);
  const display: ResearchDisplayBlock = {
    page: "contact",
    sections: [
      { key: "why-this-person", h1: "Why this person", empty: personItems.length === 0, defaultOpen: true, restricted: false, items: personItems },
      ...relatedSections,
      {
        key: "account-context", h1: "Account context", empty: false, defaultOpen: false, restricted: false,
        items: zafranSpecContent.overviewDisplay.sections.filter((section) => !section.restricted)
          .flatMap((section) => section.items).filter((item) => item.contactRefs.some((ref) => ref.contactId === summary.id)),
      },
      { ...zafranSpecContent.overviewDisplay.sections.find((section) => section.key === "watch-outs")!, key: "do-not-mention", h1: "Do not mention" },
    ].map((section) => ({ ...section, empty: section.items.length === 0, emptyMessage: `No ${section.h1.toLowerCase()} information found for ${summary.name}.` })),
  };
  return {
    ...summary,
    accountId: "zafran-security",
    accountName: "Zafran Security",
    accountLogoPath: "/logos/zafran.svg",
    recentSignalsLabel: researchCountLabel(display.sections),
    linkedinLabel: linkedinUrl.replace(/^https?:\/\/(www\.)?/, ""),
    linkedinUrl,
    emailLabel,
    reports: [],
    overviewParagraphs: personItems.flatMap((item) => item.body.map((sentence) => sentence.text)),
    evidence: [],
    researchEvidence: zafranSpecContent.evidence,
    contactDisplay: display,
  };
}

export const zafranContactDetails: Record<string, AccountContactDetail> = {
  "nick-fisher": nickFisherFixture,
  "vari-kaur": compactDetail(
    zafranContactsFixture[1]!,
    "https://www.linkedin.com/in/varinderkaur",
    "vari@zafran.io",
  ),
  "sanaz-yashar": compactDetail(
    zafranContactsFixture[2]!,
    "https://www.linkedin.com/in/sanaz-yashar",
    "sanaz@zafran.io",
  ),
  "tom-anthony": compactDetail(
    zafranContactsFixture[3]!,
    "https://www.linkedin.com/in/tomanthonyjr",
    "tom@zafran.io",
  ),
  "ben-seri": compactDetail(
    zafranContactsFixture[4]!,
    "https://www.linkedin.com/in/ben-seri",
  ),
};
