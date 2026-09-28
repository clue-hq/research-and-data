import type {
  AccountContactDetail,
  AccountContactSummary,
  ContactPersonaTone,
} from "../../model/account-contact";
import { zafranContactReferences } from "./account";
import { zafranResearchEvidence } from "./evidence";
import { buildZafranSpecContent, fieldText, zafranNickCore as core } from "./spec-content";
import { researchCountLabel } from "../../model/research-presentation";
import type {
  ResearchDisplayBlock,
  ResearchEvidence,
} from "../../model/research-display";

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

/**
 * The date the Zafran research ran. The fixture stands in for the backend, so
 * every label it manufactures is pinned to that date — never to the clock the
 * page happens to render on.
 */
const RESEARCHED_ON = "2026-09-02";

/**
 * The tenure wording the backend serves as `tenureLabel` (contract v1, ruling
 * R8). It lives here, in the fixture, because it is the backend's label to
 * write; the contact page prints `tenureLabel` and computes nothing.
 */
export function formatTenure(start: string, asOf: string) {
  const from = new Date(`${start}T00:00:00Z`);
  const to = new Date(`${asOf}T00:00:00Z`);
  const months = Math.max(0, (to.getUTCFullYear() - from.getUTCFullYear()) * 12 + to.getUTCMonth() - from.getUTCMonth() - (to.getUTCDate() < from.getUTCDate() ? 1 : 0));
  const parts = [Math.floor(months / 12) ? `${Math.floor(months / 12)} year${months >= 24 ? "s" : ""}` : "", months % 12 ? `${months % 12} month${months % 12 === 1 ? "" : "s"}` : ""].filter(Boolean);
  return `${from.toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" })} (${parts.join(" ") || "less than a month"})`;
}

/** The claim id of the work-email record behind a contact's email chip (ruling R5). */
function emailClaimIdFor(emailLabel: string | undefined) {
  return emailLabel ? `email-${emailLabel.slice(0, emailLabel.indexOf("@"))}` : null;
}

/**
 * The served `lastModifiedAt`: the latest `verifiedAt` among the claims THIS
 * contact's page cites (ruling R8). Reading the account's whole evidence set
 * here would reproduce the very defect R8 fixes — a person "updated" whenever
 * anything on the account was.
 */
function latestVerifiedAt(
  display: ResearchDisplayBlock,
  records: ResearchEvidence[],
) {
  const cited = new Set(
    display.sections.flatMap((section) => [
      ...(section.intro ?? []).flatMap((sentence) => sentence.claimIds),
      ...section.items.flatMap((item) => [
        ...item.body.flatMap((sentence) => sentence.claimIds),
        ...(item.sendLine?.claimIds ?? []),
      ]),
    ]),
  );
  const latest = records
    .filter((record) => cited.has(record.claimId))
    .map((record) => record.verifiedAt)
    .sort()
    .at(-1);
  return `${latest ?? RESEARCHED_ON}T00:00:00.000Z`;
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
  emailClaimId: emailClaimIdFor(fieldText(core.Email!)),
  locationLabel,
  bestFirstChannelLabel: core["Best first channel"],
  educationLabel: fieldText(core.Education!),
  employmentStartedAt,
  tenureLabel: formatTenure(employmentStartedAt, RESEARCHED_ON),
  linkedinFollowers: Number(core.LinkedIn!.match(/([\d,]+) followers/)![1]!.replace(/,/g, "")),
  linkedinCreator: core.LinkedIn!.includes("creator"),
  locationClaimId: "nick-location",
  reports: [vari],
  overviewParagraphs: zafranSpecContent.contactDisplay.sections[0]!.items[0]!.body.map((sentence) => sentence.text),
  evidence: [],
  customFields: [],
  researchEvidence: [...zafranSpecContent.evidence, {
    ...zafranResearchEvidence.find((record) => record.claimId === "ashby-bdr-role")!,
    claimId: "nick-location",
    quote: null,
    researchExcerpt: locationLabel,
  }],
  contactDisplay: zafranSpecContent.contactDisplay,
  lastModifiedAt: latestVerifiedAt(
    zafranSpecContent.contactDisplay,
    zafranSpecContent.evidence,
  ),
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
      { key: "why-this-person", h1: "Why this person", empty: personItems.length === 0, defaultOpen: true, pending: false, restricted: false, items: personItems },
      ...relatedSections,
      // Ruling R10: "Account context" is fixture-only — it exists so the four
      // non-Nick pages have the spec's content. Production sections come from
      // `contactDisplay` alone, and no component switches on this key.
      {
        key: "account-context", h1: "Account context", empty: false, defaultOpen: false, pending: false, restricted: false,
        items: zafranSpecContent.overviewDisplay.sections.filter((section) => !section.restricted)
          .flatMap((section) => section.items).filter((item) => item.contactRefs.some((ref) => ref.contactId === summary.id)),
      },
      { ...zafranSpecContent.overviewDisplay.sections.find((section) => section.key === "watch-outs")!, key: "do-not-mention", h1: "Do not mention" },
      { ...zafranSpecContent.contactDisplay.sections.find((section) => section.key === "miscellaneous")! },
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
    emailClaimId: emailClaimIdFor(emailLabel),
    reports: [],
    overviewParagraphs: personItems.flatMap((item) => item.body.map((sentence) => sentence.text)),
    evidence: [],
    customFields: [],
  researchEvidence: zafranSpecContent.evidence,
    contactDisplay: display,
    lastModifiedAt: latestVerifiedAt(display, zafranSpecContent.evidence),
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
