import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { zafranAccountDetailFixture as account, zafranContactReferences } from "./account";
import { zafranContactDetails as contacts, nickFisherFixture as nick } from "./contacts";
import { zafranWorkspaceFixture as workspace } from "./insights";
import { accountFixtures } from "../accounts.fixture";
import { isNewResearch } from "../../model/research-presentation";
import { formatTenure } from "./contacts";
import { filterAccounts } from "../../model/account-query";
import { buildZafranSpecContent, fieldText, zafranAccountCore, zafranAccountCustom, zafranNickCore } from "./spec-content";
import { zafranResearchEvidence } from "./evidence";

const md = readFileSync("src/features/accounts/data/zafran/FRONTEND-SPEC-ZAFRAN.md", "utf8");
const insights = workspace.insightsDisplay!;
const evidence = new Map(workspace.researchEvidence.map((record) => [record.claimId, record]));
const section = (key: string) => insights.sections.find((entry) => entry.key === key)!;

test("all authored priorities remain available, including every P3 item", () => {
  assert.equal(section("buying-signals").items.length, 4);
  assert.equal(section("money-and-momentum").items.length, 3);
  assert.equal(section("contact-insights").items.length, 5);
  assert.equal(section("contact-insights").items.at(-1)!.priority, 3);
  assert.equal(insights.sections.flatMap((entry) => entry.items).length, 21);
});

test("fit dispositions retain five supporting facts and two caveats", () => {
  assert.deepEqual(account.overviewDisplay!.sections[1]!.items.map((item) => item.fitDisposition), ["support", "support", "support", "support", "support", "caveat", "caveat"]);
});

test("instruction text never becomes contact research", () => {
  assert.doesNotMatch(JSON.stringify(nick.contactDisplay), /Empty-state line|\{section\}|Part 5|Link register/);
  // By key, not position: Miscellaneous (added 2026-09-27, 296922df1) is now the last section.
  const doNotMention = nick.contactDisplay!.sections.find((entry) => entry.key === "do-not-mention")!;
  assert.equal(doNotMention.items.at(-1)!.body.length, 0);
});

test("the same URL resolves to distinct Gong and buying-criteria evidence", () => {
  const gong = section("tools-they-already-use").items[2]!;
  const criteria = section("contact-insights").items[1]!;
  const a = evidence.get(gong.body[0]!.claimIds[0]!)!;
  const b = evidence.get(criteria.body[0]!.claimIds[0]!)!;
  assert.equal(a.sourceUrl, b.sourceUrl);
  assert.notEqual(a.claimId, b.claimId);
  assert.match(a.researchExcerpt!, /Gong calls/);
  assert.match(b.researchExcerpt!, /3 basic criteria/);
  assert.equal(a.quote, null, "No fabricated original-source quotation");
});

test("each media reference retains its specific supplied timestamp", () => {
  const openers = nick.contactDisplay!.sections.find((entry) => entry.key === "openers")!;
  const angles = nick.contactDisplay!.sections.find((entry) => entry.key === "angles")!;
  const media = (ids: string[]) => ids.map((id) => evidence.get(id)!).find((record) => record.sourceDomain === "youtube.com")!;
  assert.equal(media(openers.items[1]!.body[0]!.claimIds).mediaTimestamp, "00:05–00:30");
  assert.equal(media(angles.items[0]!.body[0]!.claimIds).mediaTimestamp, "00:30");
});

test("consecutive citations stay after their sentence punctuation, not around a stray dot", () => {
  const opener = nick.contactDisplay!.sections.find((entry) => entry.key === "openers")!.items[1]!;
  const first = opener.body[0]!.segments![0]!;
  assert.equal(first.claimIds.length, 2);
  assert.match(first.text, /Movies"\.$/);
  assert.ok(opener.body[0]!.segments!.every((segment) => !/^[,.;:!?]$/.test(segment.text.trim())));
});

test("a same-post quote does not become evidence for the following profile citation", () => {
  const vari = section("contact-insights").items[0]!;
  const profile = vari.body[0]!.claimIds.map((id) => evidence.get(id)!).find((entry) => entry.sourceUrl?.endsWith("/in/varinderkaur"))!;
  assert.match(profile.researchExcerpt!, /^She holds 6sense/);
  assert.doesNotMatch(profile.researchExcerpt!, /Looking for someone/);
});

test("every public URL in the source register is retained", () => {
  const urls = [...md.slice(md.indexOf("## Part 5")).matchAll(/\| (https?:\/\/\S+)/g)].map((match) => match[1]!).filter((url) => !url.startsWith("https://www.google.com"));
  const retained = workspace.researchEvidence.filter((record) => record.claimId.startsWith("register-")).map((record) => record.sourceUrl);
  assert.deepEqual(retained, urls);
});

test("the supplied link register resolves sources without a duplicate hand-written record", () => {
  const result = buildZafranSpecContent({ contacts: zafranContactReferences, evidence: zafranResearchEvidence.filter((record) => record.sourceDomain !== "jobs.ashbyhq.com") });
  const claim = result.insightsDisplay.sections[0]!.items[0]!.body[0]!.claimIds[0]!;
  assert.equal(result.evidence.find((record) => record.claimId === claim)!.sourceDomain, "jobs.ashbyhq.com");
});

test("core and custom fields use the supplied record while hiding display annotations", () => {
  assert.equal(account.headcountLabel, zafranAccountCore.Headcount);
  assert.equal(account.fundingLabel, zafranAccountCore.Funding);
  assert.equal(account.locationsLabel, zafranAccountCore.HQ);
  assert.deepEqual(account.customFields.map(({ label, value }) => [label, value]), Object.entries(zafranAccountCustom));
  assert.equal(nick.title, fieldText(zafranNickCore.Title!));
  assert.equal(nick.emailLabel, "nick@zafran.io");
  assert.equal(nick.educationLabel, "Columbia Business School MBA (2013) · Vassar BA");
  assert.equal(nick.linkedinFollowers, 6808);
  assert.equal(nick.linkedinCreator, true);
  assert.doesNotMatch(nick.locationLabel!, /verified|record/);
});

test("every committee cell preserves supplied text and reach links without account follower metadata", () => {
  const rows = md.slice(md.indexOf("## Buying committee"), md.indexOf("## How to approach")).split("\n").filter((line) => line.startsWith("| →"));
  assert.equal(account.buyingCommittee.length, rows.length);
  rows.forEach((line, index) => {
    const cells = line.split("|").map((cell) => cell.trim());
    const member = account.buyingCommittee[index]!;
    assert.deepEqual([member.name, member.title, member.persona, member.whyTheyMatter], [cells[1]!.replace(/^→\s*/, ""), cells[2], cells[3], cells[5]]);
    assert.ok(member.linkedinUrl && cells[4]!.includes(member.linkedinUrl));
    if (member.email) assert.ok(cells[4]!.includes(member.email));
  });
});

test("contact references preserve authored order and named subject identity", () => {
  assert.deepEqual(section("buying-signals").items[0]!.contactRefs.map((ref) => ref.name), ["Vari Kaur", "Nick Fisher"]);
  assert.deepEqual(section("contact-insights").items.map((item) => item.subject?.name), ["Vari Kaur", "Nick Fisher", "Sanaz Yashar", "Tom Anthony", "Ben Seri"]);
  assert.ok(account.overviewDisplay!.sections.find((entry) => entry.key === "how-to-approach")!.items[0]!.contactRefs.length === 4);
});

test("all five contact pages carry sourced content and explicit warning sections", () => {
  for (const contact of Object.values(contacts)) {
    assert.ok(contact.contactDisplay);
    assert.ok(contact.contactDisplay.sections[0]!.items.length);
    assert.ok(contact.contactDisplay.sections.some((entry) => entry.restricted));
    assert.doesNotMatch(contact.recentSignalsLabel, /verified signals/);
  }
  for (const item of section("contact-insights").items.filter((item) => item.subject?.contactId !== "nick-fisher")) {
    const destination = contacts[item.subject!.contactId]!;
    assert.deepEqual(destination.contactDisplay!.sections[0]!.items[0], item);
  }
});

test("list, detail, preview data have one score, socials, dates and custom fields", () => {
  const row = accountFixtures.find((entry) => entry.id === account.id)!;
  for (const key of ["fitScore", "socials", "createdAt", "lastModifiedAt", "industryLabels", "customFields", "researchStatusLabel", "websiteUrl"] as const) assert.deepEqual(row[key], account[key]);
  assert.equal(row.fitScore, null);
  assert.equal(filterAccounts([row], [{ id: "score", field: "fitScore", operator: "less-than", value: "10", join: "and" }]).length, 0, "Unknown is not zero");
});

test("freshness requires a real earlier visit and tenure follows the start date", () => {
  const item = section("buying-signals").items[0]!;
  assert.equal(isNewResearch(item, evidence, null), false);
  assert.equal(isNewResearch(item, evidence, "2026-09-01T00:00:00Z"), true);
  assert.equal(isNewResearch(item, evidence, "2026-09-05T00:00:00Z"), false);
  assert.equal(formatTenure("2024-04-01", "2026-09-05"), "April 2024 (2 years 5 months)");
  assert.equal(formatTenure("2024-04-01", "2026-10-05"), "April 2024 (2 years 6 months)");
});

// Independent text inventory: compare every authored priority block, not a few
// representative phrases. Only display annotations/markup are excluded.
function words(value: string) {
  return value.replace(/\[[^\]]*]\(https?:\/\/[^)]+\)/g, "")
    .replace(/·\s*(?:(?:posted|verified|record)\s+)?(?:\d{1,2} [A-Z][a-z]{2} \d{4}|\d{2}:\d{2}(?:–\d{2}:\d{2})?)/g, "")
    .replace(/→\s*(?:Vari Kaur|Nick Fisher|Sanaz Yashar|Tom Anthony|Ben Seri)/g, "")
    .replace(/\(P[123]\)|\[Copy]/g, "")
    .match(/[\p{L}\p{N}]+/gu) ?? [];
}

test("all 34 authored priority blocks preserve every word, number and copy line", () => {
  const blocks = [...md.matchAll(/^\*\*(?!→)(.+)\*\*\s*\(P[123]\)\n([\s\S]*?)(?=\n\s*\n)/gm)];
  const items = [...insights.sections, ...nick.contactDisplay!.sections].flatMap((entry) => entry.items);
  assert.equal(blocks.length, 34);
  for (const match of blocks) {
    const item = items.find((entry) => entry.h2 === match[1]);
    assert.ok(item, `Missing item ${match[1]}`);
    const actual = [item.h2, ...item.body.map((sentence) => sentence.text), item.sendLine ? `${item.sendLine.channel} ${item.sendLine.text}` : ""].join(" ");
    assert.deepEqual(words(actual), words(match[0]), `Altered or omitted text: ${item.h2}`);
  }
});

test("every overview paragraph, fit reason, timing item, approach and warning is preserved", () => {
  const boundaries = [
    ["what-they-do", "## What Zafran does", "## Why they fit"],
    ["why-they-fit", "## Why they fit", "## Why now"],
    ["why-now", "## Why now", "## Buying committee"],
    ["how-to-approach", "## How to approach", "## 🔒 Watch-outs"],
    ["watch-outs", "## 🔒 Watch-outs", "## Right rail"],
  ];
  for (const [key, start, end] of boundaries) {
    const entry = account.overviewDisplay!.sections.find((section) => section.key === key)!;
    const raw = md.slice(md.indexOf("\n", md.indexOf(start!)) + 1, md.indexOf(end!, md.indexOf(start!)))
      .replace(/^\d+\.\s+/gm, "");
    const actual = [...(entry.intro ?? []).map((p) => p.text), ...entry.items.map((item) => [item.h2, ...item.body.map((p) => p.text)].join(" "))].join(" ");
    assert.deepEqual(words(actual), words(raw), `Overview content lost: ${key}`);
  }
});

test("all restricted research is retained without implementation instructions", () => {
  const pairs = [
    [section("context-only"), "## 🔒 Context only — never use in outreach", "---\n\n## Part 3"],
    [nick.contactDisplay!.sections.find((entry) => entry.key === "do-not-mention")!, "## 🔒 Do not mention", "**Empty-state line"],
  ] as const;
  for (const [entry, start, end] of pairs) {
    const raw = md.slice(md.indexOf("\n", md.indexOf(start)) + 1, md.indexOf(end, md.indexOf(start)));
    assert.deepEqual(words(entry.items.map((item) => [item.h2, ...item.body.map((p) => p.text)].join(" ")).join(" ")), words(raw));
  }
});

test("every source reference resolves, including paragraph introductions and copied text", () => {
  for (const display of [account.overviewDisplay!, insights, ...Object.values(contacts).map((contact) => contact.contactDisplay!)]) {
    for (const entry of display.sections) {
      const ids = [
        ...(entry.intro ?? []).flatMap((sentence) => sentence.claimIds),
        ...entry.items.flatMap((item) => [...item.body.flatMap((sentence) => sentence.claimIds), ...(item.sendLine?.claimIds ?? [])]),
      ];
      for (const id of ids) assert.ok(evidence.has(id), `Unresolved ${id}`);
    }
  }
});
