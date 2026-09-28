import { readFileSync } from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import type {
  ResearchContactReference,
  ResearchDisplayBlock,
  ResearchEvidence,
  ResearchInlineSegment,
  ResearchItem,
  ResearchSection,
  ResearchSentence,
  BuyingCommitteeMember,
} from "../../model/research-display";

const specPath = path.join(
  process.cwd(),
  "src/features/accounts/data/zafran/FRONTEND-SPEC-ZAFRAN.md",
);

const specMarkdown = readFileSync(specPath, "utf8");

type ContactReferences = Record<string, ResearchContactReference>;

type BuildSpecOptions = {
  contacts: ContactReferences;
  evidence: ResearchEvidence[];
};

export type ZafranSpecContent = {
  evidence: ResearchEvidence[];
  buyingCommittee: BuyingCommitteeMember[];
  contactDisplay: ResearchDisplayBlock;
  insightsDisplay: ResearchDisplayBlock;
  insightSummary: string[];
  overviewDisplay: ResearchDisplayBlock;
};

function normalizeWhitespace(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function cleanInlineText(value: string) {
  return value.replace(/\*\*/g, "").replace(/`/g, "").replace(/\p{Extended_Pictographic}\uFE0F?/gu, "");
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function slug(value: string) {
  return value
    .toLowerCase()
    .replace(/[’'“”"]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 64);
}

function sectionBody(startHeading: string, endHeading?: string) {
  const start = specMarkdown.indexOf(startHeading);
  if (start === -1) throw new Error(`Missing Zafran spec heading: ${startHeading}`);
  const contentStart = specMarkdown.indexOf("\n", start) + 1;
  const end = endHeading
    ? specMarkdown.indexOf(endHeading, contentStart)
    : specMarkdown.length;
  if (endHeading && end === -1) {
    throw new Error(`Missing Zafran spec heading: ${endHeading}`);
  }
  return specMarkdown.slice(contentStart, end);
}

const sourceIndexes = new WeakMap<ResearchEvidence[], Map<string, ResearchEvidence[]>>();

function sourceIndex(evidence: ResearchEvidence[]) {
  const cached = sourceIndexes.get(evidence);
  if (cached) return cached;
  const byUrl = new Map<string, ResearchEvidence[]>();
  for (const record of evidence) {
    if (!record.sourceUrl) continue;
    const records = byUrl.get(record.sourceUrl) ?? [];
    records.push(record);
    byUrl.set(record.sourceUrl, records);
  }
  sourceIndexes.set(evidence, byUrl);
  return byUrl;
}

function fields(start: string, end: string) {
  return Object.fromEntries(sectionBody(start, end).split("\n").flatMap((line) => {
    const match = line.match(/^- ([^:]+):\s*(.+)$/);
    return match ? [[match[1]!, match[2]!]] : [];
  }));
}

export const zafranAccountCore = fields("## Right rail", "**Custom**");
export const zafranAccountCustom = fields("**Custom**", "**Contacts**");
export const zafranNickCore = fields("**Core rail**", "## Why this person");
const researchMetadata = specMarkdown.match(/^\*\*Top strip:\*\* (\d+) insights · (\d+) people · (Researched [^·\n]+)/m)!;

export function fieldText(value: string) {
  return normalizeWhitespace(cleanInlineText(value)
    .replace(/\[([^\]]+)]\(https?:\/\/[^)]+\)/g, "$1")
    .replace(/\s*·\s*(?:posted|verified|record)\s+\d{1,2} [A-Z][a-z]{2} \d{4}/g, "")
    .replace(/\s*✓\s*verified\s+\d{1,2} [A-Z][a-z]{2} \d{4}/g, "")
    .replace(/→\s*/g, ""));
}

function buyingCommittee(options: BuildSpecOptions): BuyingCommitteeMember[] {
  return sectionBody("## Buying committee", "## How to approach").split("\n").filter((line) => line.startsWith("| →")).map((line) => {
    const cells = line.split("|").map((value) => value.trim());
    const name = cells[1]!.replace(/^→\s*/, "");
    const ref = Object.values(options.contacts).find((contact) => contact.name === name);
    if (!ref) throw new Error(`Missing contact destination: ${name}`);
    const email = cells[4]!.match(/[\w.+-]+@[\w.-]+\.[a-z]+/i)?.[0] ?? null;
    const linkedinUrl = cells[4]!.match(/\]\((https:\/\/www.linkedin.com\/[^)]+)\)/)?.[1];
    if (!linkedinUrl) throw new Error(`Missing LinkedIn locator: ${name}`);
    return { contactId: ref.contactId, name, title: cells[2]!, persona: cells[3]!, email,
      emailClaimId: email ? options.evidence.find((record) => record.researchExcerpt?.includes(email))?.claimId ?? null : null,
      linkedinUrl, whyTheyMatter: cells[5]!,
    };
  });
}

function claimForUrl(
  url: string,
  evidenceByUrl: Map<string, ResearchEvidence[]>,
  restricted: boolean,
  excerpt: string,
  annotation: string,
) {
  const records = evidenceByUrl.get(url);
  if (!records?.length) {
    throw new Error(`Missing evidence for Zafran spec URL: ${url}`);
  }
  const source = records[0]!;
  const claimId = `spec-${createHash("sha256").update(JSON.stringify([url, excerpt, annotation, restricted])).digest("hex").slice(0, 20)}`;
  const date = annotation.match(/(?:verified|record)\s+(\d{1,2} [A-Z][a-z]{2} \d{4})/)?.[1];
  const timestamp = annotation.match(/\b\d{2}:\d{2}(?:–\d{2}:\d{2})?/)?.[0] ?? null;
  // A URL identifies a document, not an evidence span. Keep each supplied
  // citation's exact context; never dress a research summary up as a quotation.
  evidenceByUrl.set(claimId, [{
    ...source,
    claimId,
    quote: null,
    researchExcerpt: excerpt,
    verifiedAt: date ? new Date(`${date} UTC`).toISOString().slice(0, 10) : source.verifiedAt,
    verificationKind: annotation.includes("record") ? "record" : "verified",
    mediaTimestamp: timestamp,
    outreachSafe: !restricted,
  }]);
  return claimId;
}

const sourceAnnotation =
  /^(?:\s*·\s*(?:(?:posted|verified|record)\s+)?(?:\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4}|\d{2}:\d{2}(?:–\d{2}:\d{2})?))+/;

function inlineSentence(
  markdown: string,
  evidenceByUrl: Map<string, ResearchEvidence[]>,
  restricted = false,
  fallbackText = "",
): ResearchSentence {
  const normalized = normalizeWhitespace(markdown);
  const segments: ResearchInlineSegment[] = [];
  const sourceToken =
    /\[([^\]]+)]\((https?:\/\/[^)]+)\)|(\s*·\s*record\s+\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4})/g;
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = sourceToken.exec(normalized))) {
    const before = cleanInlineText(
      normalized.slice(cursor, match.index),
    ).trimEnd();
    // "(same post)" explicitly attributes that preceding sentence to the
    // previous citation. Do not show it as evidence for the following profile.
    const citationContext = before.includes("(same post).")
      ? before.slice(before.lastIndexOf("(same post).") + "(same post).".length).trim()
      : before.trim();
    const claimId = match[2]
      ? claimForUrl(
          match[2], evidenceByUrl, restricted,
          citationContext && !/^·$/.test(citationContext)
            ? citationContext
            : segments.at(-1)?.text.trim() || fallbackText,
          normalized.slice(sourceToken.lastIndex).match(sourceAnnotation)?.[0] ?? "",
        )
      : normalized.slice(Math.max(0, match.index - 120), match.index).includes("167 employees")
        ? "zafran-headcount-record"
        : "zafran-revenue-estimate";
    const text = /^\s*·\s*$/.test(before) ? "" : before;
    const previous = segments.at(-1);
    // Adjacent citations share a sentence. Attach both before moving its final
    // punctuation, rather than leaving a standalone dot between two chips.
    if (!text.trim() && previous?.claimIds.length) previous.claimIds.push(claimId);
    else segments.push({ text, claimIds: [claimId] });

    cursor = sourceToken.lastIndex;
    if (match[2]) {
      const annotation = normalized.slice(cursor).match(sourceAnnotation)?.[0];
      if (annotation) cursor += annotation.length;
      sourceToken.lastIndex = cursor;
    }
  }

  const remainder = cleanInlineText(normalized.slice(cursor));
  if (remainder || segments.length === 0) {
    segments.push({ text: remainder, claimIds: [] });
  }

  for (let index = 1; index < segments.length; index += 1) {
    const previous = segments[index - 1]!;
    const current = segments[index]!;
    if (previous.claimIds.length === 0) continue;
    const punctuation = current.text.match(/^([,.;:!?])/);
    if (!punctuation) continue;
    previous.text = `${previous.text}${punctuation[1]}`;
    current.text = current.text.slice(punctuation[1].length);
  }

  const displaySegments = segments.filter(
    (segment) => segment.text || segment.claimIds.length > 0,
  );

  return {
    text: displaySegments.map((segment) => segment.text).join(""),
    claimIds: Array.from(
      new Set(displaySegments.flatMap((segment) => segment.claimIds)),
    ),
    segments: displaySegments,
  };
}

function refsForText(text: string, contacts: ContactReferences) {
  return Object.values(contacts).map((contact) => ({
    contact,
    index: text.search(new RegExp(`\\b${escapeRegExp(contact.name)}\\b|\\b${escapeRegExp(contact.name.split(" ")[0]!)}\\b`, "i")),
  })).filter(({ index }) => index >= 0).sort((a, b) => a.index - b.index).map(({ contact }) => contact);
}

function removeContactArrows(
  value: string,
  contacts: ContactReferences,
) {
  let result = value;
  for (const contact of Object.values(contacts)) {
    result = result.replace(
      new RegExp(`\\s*→\\s*${escapeRegExp(contact.name)}`, "gi"),
      "",
    );
  }
  return result.trim();
}

function parseSendLine(
  value: string,
  evidenceByUrl: Map<string, ResearchEvidence[]>,
  restricted: boolean,
) {
  const normalized = normalizeWhitespace(value)
    .replace(/^>\s*/, "")
    .replace(/\s*\[Copy]\s*$/, "");
  const match = normalized.match(/^\*\*(.+?):\*\*\s*(.*)$/);
  if (!match) return null;
  const sentence = inlineSentence(match[2]!, evidenceByUrl, restricted);
  return {
    channel: match[1]!,
    text: sentence.text,
    claimIds: sentence.claimIds,
  };
}

function splitMeaning(value: string) {
  const marker = "What it means for us:";
  const index = value.indexOf(marker);
  if (index === -1) return [value];
  return [value.slice(0, index), value.slice(index)];
}

function parsePriorityItem(
  block: string,
  index: number,
  prefix: string,
  options: BuildSpecOptions,
  restricted = false,
  newSinceLastVisit = false,
): ResearchItem {
  const lines = block.split("\n").map((line) => line.trim());
  const allText = normalizeWhitespace(block);
  const explicitNames = [...allText.matchAll(/→\s*(Vari Kaur|Nick Fisher|Sanaz Yashar|Tom Anthony|Ben Seri)/g)].map((match) => match[1]);
  const mentioned = refsForText(allText, options.contacts);
  const contactRefs = [...new Map([
    ...explicitNames.map((name) => Object.values(options.contacts).find((contact) => contact.name === name)!),
    ...mentioned,
  ].map((contact) => [contact.contactId, contact])).values()];

  const subjectLine = /^\*\*→/.test(lines[0] ?? "") ? lines.shift() : undefined;
  const heading = lines.shift()?.match(/^\*\*(.+)\*\*\s*\(P([123])\)$/);
  if (!heading) throw new Error(`Could not parse Zafran spec item: ${block}`);

  const sendIndex = lines.findIndex((line) => line.startsWith(">"));
  const bodyLines = sendIndex === -1 ? lines : lines.slice(0, sendIndex);
  const sendLines = sendIndex === -1 ? [] : lines.slice(sendIndex);
  const bodyMarkdown = removeContactArrows(
    normalizeWhitespace(bodyLines.join(" ")),
    options.contacts,
  );
  const evidenceByUrl = sourceIndex(options.evidence);

  return {
    id: `${prefix}-${index + 1}-${slug(heading[1]!)}`,
    h2: heading[1]!,
    body: splitMeaning(bodyMarkdown)
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => inlineSentence(part, evidenceByUrl, restricted, heading[1]!)),
    sendLine: sendLines.length
      ? parseSendLine(sendLines.join(" "), evidenceByUrl, restricted)
      : null,
    contactRefs,
    subject: subjectLine ? refsForText(subjectLine, options.contacts)[0] : undefined,
    priority: Number(heading[2]) as 1 | 2 | 3,
    newSinceLastVisit,
  };
}

function blockList(value: string) {
  return value
    .trim()
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean);
}

function parsePrioritySection(
  key: string,
  h1: string,
  body: string,
  options: BuildSpecOptions,
  config: { newCount?: number; restricted?: boolean } = {},
): ResearchSection {
  const blocks = blockList(body).filter((block) => block.startsWith("**"));
  return {
    key,
    h1,
    empty: false,
    restricted: config.restricted ?? false,
    defaultOpen: key === "buying-signals" || key === "why-this-person",
    pending: false,
    intro: [],
    items: blocks.map((block, index) =>
      parsePriorityItem(
        block,
        index,
        key,
        options,
        config.restricted,
        index < (config.newCount ?? 0),
      ),
    ),
  };
}

function groupedLines(value: string, startsGroup: (line: string) => boolean) {
  const groups: string[][] = [];
  for (const line of value.trim().split("\n")) {
    if (startsGroup(line)) groups.push([line]);
    else if (groups.length) groups.at(-1)!.push(line);
  }
  return groups.map((lines) => normalizeWhitespace(lines.join(" ")));
}

function parseBulletSection(
  key: string,
  h1: string,
  body: string,
  options: BuildSpecOptions,
  restricted = false,
): ResearchSection {
  const evidenceByUrl = sourceIndex(options.evidence);
  const content = body.split("**Empty-state line")[0]!;
  const items = groupedLines(content, (line) => line.startsWith("- ")).map(
    (group, index) => {
      const match = group.match(/^- \*\*(.+?)\*\*\s*(.*)$/);
      const plainText = cleanInlineText(group.replace(/^-\s*/, ""));
      const heading = match?.[1] ?? plainText;
      const bodyText = removeContactArrows(match?.[2] ?? "", options.contacts);
      return {
        id: `${key}-${index + 1}-${slug(heading)}`,
        h2: heading,
        body: bodyText
          ? [inlineSentence(bodyText, evidenceByUrl, restricted, heading)]
          : [],
        sendLine: null,
        contactRefs: refsForText(group, options.contacts),
        priority: 3 as const,
        newSinceLastVisit: false,
      };
    },
  );
  return {
    key,
    h1,
    empty: false,
    restricted,
    defaultOpen: false,
    pending: false,
    intro: [],
    items,
  };
}

function parseFitSection(body: string, options: BuildSpecOptions) {
  const evidenceByUrl = sourceIndex(options.evidence);
  const items = groupedLines(body, (line) => /^[✓✗]\s+\*\*/.test(line)).map(
    (group, index) => {
      const match = group.match(/^[✓✗]\s+\*\*(.+?)\*\*\s*(.*)$/);
      if (!match) throw new Error(`Could not parse Zafran fit item: ${group}`);
      return {
        id: `why-they-fit-${index + 1}-${slug(match[1]!)}`,
        h2: match[1]!,
        body: [inlineSentence(match[2]!, evidenceByUrl)],
        sendLine: null,
        contactRefs: refsForText(group, options.contacts),
        priority: index === 1 || index === 2 ? (1 as const) : (2 as const),
        fitDisposition: group.startsWith("✗") ? "caveat" as const : "support" as const,
        newSinceLastVisit: false,
      };
    },
  );
  return {
    key: "why-they-fit",
    h1: "Why they fit",
    empty: false,
    restricted: false,
    defaultOpen: true,
    pending: false,
    intro: [],
    items,
  } satisfies ResearchSection;
}

function parseNumberedSection(body: string, options: BuildSpecOptions) {
  const evidenceByUrl = sourceIndex(options.evidence);
  const items = groupedLines(body, (line) => /^\d+\.\s+\*\*/.test(line)).map(
    (group, index) => {
      const match = group.match(/^\d+\.\s+\*\*(.+?)\*\*\s*(.*)$/);
      if (!match) throw new Error(`Could not parse Zafran numbered item: ${group}`);
      const bodyText = removeContactArrows(match[2]!, options.contacts);
      return {
        id: `why-now-${index + 1}-${slug(match[1]!)}`,
        h2: match[1]!,
        body: bodyText ? [inlineSentence(bodyText, evidenceByUrl)] : [],
        sendLine: null,
        contactRefs: refsForText(group, options.contacts),
        inlineLead: true,
        priority: 1 as const,
        newSinceLastVisit: false,
      };
    },
  );
  return {
    key: "why-now",
    h1: "Why now",
    empty: false,
    restricted: false,
    defaultOpen: true,
    pending: false,
    intro: [],
    items,
  } satisfies ResearchSection;
}

function parseLabeledParagraphs(
  key: string,
  h1: string,
  body: string,
  options: BuildSpecOptions,
) {
  const evidenceByUrl = sourceIndex(options.evidence);
  return {
    key,
    h1,
    empty: false,
    restricted: false,
    defaultOpen: false,
    pending: false,
    intro: [],
    items: blockList(body)
      .filter((block) => block.startsWith("**"))
      .map((block, index) => {
        const normalized = normalizeWhitespace(block);
        const match = normalized.match(/^\*\*(.+?)\*\*\s*(.*)$/);
        if (!match) throw new Error(`Could not parse Zafran paragraph: ${block}`);
        return {
          id: `${key}-${index + 1}-${slug(match[1]!)}`,
          h2: match[1]!,
          body: [inlineSentence(match[2]!, evidenceByUrl)],
          sendLine: null,
          contactRefs: refsForText(block, options.contacts),
          priority: 2 as const,
          newSinceLastVisit: false,
        };
      }),
  } satisfies ResearchSection;
}

function buildInsights(options: BuildSpecOptions): ResearchDisplayBlock {
  return {
    page: "insights",
    sections: [
      parsePrioritySection(
        "buying-signals",
        "Buying signals",
        sectionBody("### Buying signals · 4", "### Money & momentum · 3"),
        options,
      ),
      parsePrioritySection(
        "money-and-momentum",
        "Money & momentum",
        sectionBody("### Money & momentum · 3", "### Tools they already use · 3"),
        options,
      ),
      parsePrioritySection(
        "tools-they-already-use",
        "Tools they already use",
        sectionBody(
          "### Tools they already use · 3",
          "### How they sell, and who they win · 3",
        ),
        options,
      ),
      parsePrioritySection(
        "how-they-sell",
        "How they sell, and who they win",
        sectionBody(
          "### How they sell, and who they win · 3",
          "## Contact insights · 5",
        ),
        options,
      ),
      parsePrioritySection(
        "contact-insights",
        "Contact insights",
        sectionBody(
          "## Contact insights · 5",
          "## 🔒 Context only — never use in outreach",
        ),
        options,
      ),
      parseBulletSection(
        "context-only",
        "Context only",
        sectionBody(
          "## 🔒 Context only — never use in outreach",
          "---\n\n## Part 3",
        ),
        options,
        true,
      ),
      {
        key: "miscellaneous",
        h1: "Miscellaneous",
        empty: true,
        restricted: false,
        defaultOpen: false,
        pending: false,
        emptyMessage: "No additional research findings have been published yet.",
        items: [],
      },
    ],
  };
}

function buildOverview(options: BuildSpecOptions): ResearchDisplayBlock {
  const evidenceByUrl = sourceIndex(options.evidence);
  const whatZafranDoes = sectionBody("## What Zafran does", "## Why they fit");
  return {
    page: "overview",
    sections: [
      {
        key: "what-they-do",
        h1: "What Zafran does",
        empty: false,
        restricted: false,
        defaultOpen: true,
        pending: false,
        intro: blockList(whatZafranDoes).map((paragraph) =>
          inlineSentence(paragraph, evidenceByUrl),
        ),
        items: [],
      },
      parseFitSection(
        sectionBody("## Why they fit", "## Why now"),
        options,
      ),
      parseNumberedSection(
        sectionBody("## Why now", "## Buying committee"),
        options,
      ),
      parseLabeledParagraphs(
        "how-to-approach",
        "How to approach",
        sectionBody("## How to approach", "## 🔒 Watch-outs"),
        options,
      ),
      parseBulletSection(
        "watch-outs",
        "Watch-outs",
        sectionBody("## 🔒 Watch-outs", "## Right rail"),
        options,
        true,
      ),
    ],
  };
}

function buildContact(options: BuildSpecOptions): ResearchDisplayBlock {
  return {
    page: "contact",
    sections: [
      parsePrioritySection(
        "why-this-person",
        "Why this person",
        sectionBody("## Why this person", "## Their problem right now"),
        options,
      ),
      parsePrioritySection(
        "problem-right-now",
        "Their problem right now",
        sectionBody("## Their problem right now", "## Openers"),
        options,
      ),
      parsePrioritySection(
        "openers",
        "Openers",
        sectionBody("## Openers", "## Angles"),
        options,
      ),
      parsePrioritySection(
        "angles",
        "Angles",
        sectionBody("## Angles", "## 🔒 Do not mention"),
        options,
      ),
      parseBulletSection(
        "do-not-mention",
        "Do not mention",
        sectionBody("## 🔒 Do not mention", "---\n\n## Part 5"),
        options,
        true,
      ),
      {
        key: "miscellaneous",
        h1: "Miscellaneous",
        empty: true,
        restricted: false,
        defaultOpen: false,
        pending: false,
        emptyMessage: "No additional research findings have been published yet.",
        items: [],
      },
    ],
  };
}

export function buildZafranSpecContent(
  options: BuildSpecOptions,
): ZafranSpecContent {
  // Builders must be deterministic and must not append claim instances to the
  // shared catalogue when several pages request the same sample.
  options = { ...options, evidence: options.evidence.map((record) => ({
    ...record, researchExcerpt: record.researchExcerpt ?? record.quote ?? undefined, quote: null,
  })) };
  // Index the supplied register before parsing claims, so a new source in the
  // final Markdown does not require a second, hand-maintained catalogue entry.
  for (const line of sectionBody("## Part 5 — Link register").split("\n")) {
    const cells = line.split("|").map((cell) => cell.trim());
    const url = cells[2]?.match(/^https?:\/\/\S+/)?.[0];
    if (!url) continue;
    const source = options.evidence.find((record) => record.sourceUrl === url);
    const date = cells[4]?.match(/\d{1,2} [A-Z][a-z]{2} \d{4}/)?.[0];
    const posted = cells[3]?.match(/\d{1,2} [A-Z][a-z]{2} \d{4}/)?.[0];
    options.evidence.push({
      claimId: `register-${createHash("sha256").update(url).digest("hex").slice(0, 16)}`,
      sourceUrl: url, sourceDomain: cells[1]!,
      faviconUrl: `https://www.google.com/s2/favicons?domain=${cells[1]}&sz=32`,
      title: source?.title ?? (cells[2]!.slice(url.length).trim().replace(/^\(|\)$/g, "") || cells[1]!),
      quote: null,
      publishedAt: posted ? new Date(`${posted} UTC`).toISOString().slice(0, 10) : null,
      verifiedAt: date ? new Date(`${date} UTC`).toISOString().slice(0, 10) : "2026-09-02",
      verificationKind: cells[4]?.includes("record") ? "record" : "verified",
      mediaTimestamp: null, provider: null, outreachSafe: source?.outreachSafe ?? true,
    });
  }
  const insightsDisplay = buildInsights(options);
  const overviewDisplay = buildOverview(options);
  const contactDisplay = buildContact(options);
  const count = insightsDisplay.sections.reduce((total, section) => total + section.items.length, 0);
  const evidence = [...new Map([
    ...options.evidence,
    ...Array.from(sourceIndex(options.evidence).values()).flat(),
  ].map((record) => [record.claimId, record])).values()];
  return {
    evidence,
    buyingCommittee: buyingCommittee(options),
    insightsDisplay,
    overviewDisplay,
    contactDisplay,
    insightSummary: [
      `${count} insights`,
      `${researchMetadata[2]} people`,
      researchMetadata[3]!.trim(),
    ],
  };
}
