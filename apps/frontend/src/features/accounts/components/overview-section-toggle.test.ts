import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { zafranAccountDetailFixture } from "../data/zafran/account";

const renderer = readFileSync(new URL("./research-content.tsx", import.meta.url), "utf8");
const overview = renderer.slice(renderer.indexOf("export function ResearchOverview("), renderer.indexOf("export function ResearchDigest("));
const committee = renderer.slice(renderer.indexOf("export function BuyingCommitteeTable("));
const body = readFileSync(new URL("./account-research-overview.tsx", import.meta.url), "utf8");

test("overview keeps business and fit visible, stacking only timing, committee and approach", () => {
  assert.match(overview, /const stacked = isWhyNow \|\| section\.key === "how-to-approach"/);
  assert.match(overview, /const Section = stacked \? "details" : "section"/);
  assert.match(overview, /const Heading = stacked \? "summary" : "div"/);
  assert.match(overview, /className=\{stacked \? styles\.sectionToggle : undefined\}/);
  assert.match(overview, /className=\{stacked \? styles\.sectionContent : undefined\}/);
  const overviewTag = overview.match(/<Section\b[^>]+>/)?.[0];
  const committeeTag = committee.match(/<details\b[^>]+>/)?.[0];
  for (const tag of [overviewTag, committeeTag]) {
    assert.ok(tag);
    assert.doesNotMatch(tag, /\bopen\b|\bname=/);
    assert.match(tag, /styles\.readingSection/);
  }
  for (const component of [overview, committee]) {
    assert.match(component, /<h2 className=\{styles\.readingHeading\}>/);
    assert.match(component, /styles\.sectionChevron/);
  }
  assert.match(committee, /<summary className=\{styles\.sectionToggle\}>/);
  assert.match(overview, /section\.intro\.map/);
  assert.match(overview, /section\.items\.map/);
  assert.match(overview, /item\.body\.map/);
  assert.match(overview, /<FitBadge fit=\{overallFit\}/);
  assert.match(committee, /members\.map/);
  for (const field of ["Person", "Title", "Persona", "Reach", "Why they matter"]) {
    assert.ok(committee.includes(field));
  }
});

test("the served buying-committee section renders as the table, never as an ordinary section", () => {
  // D4 ruling (e): contract v1 serves `buying-committee` in the overview block.
  // Its slot is the committee TABLE, and the section's generated items are
  // dropped — the tail resumes AFTER it (`committeeIndex + 1`).
  assert.match(body, /\(section\) => section\.key === "buying-committee"/);
  assert.match(body, /servedCommitteeIndex === -1\s*\n?\s*\? committeeIndex\s*:\s*committeeIndex \+ 1/);
  assert.match(body, /<BuyingCommitteeTable[\s\S]*?members=\{account\.buyingCommittee\}/);
  // The design build's own fixture has no such section; the table keeps its
  // place immediately before How to approach.
  assert.match(body, /\(section\) => section\.key === "how-to-approach"/);
  assert.equal(
    zafranAccountDetailFixture.overviewDisplay!.sections.some(
      (section) => section.key === "buying-committee",
    ),
    false,
  );
});

test("Watch-outs is omitted from shared overview rendering, not erased from the source data", () => {
  assert.match(body, /\(section\) => section\.key !== "watch-outs"/);
  const sections = zafranAccountDetailFixture.overviewDisplay!.sections;
  assert.equal(sections.find((section) => section.key === "watch-outs")!.items.length, 3);
  assert.deepEqual(sections.filter((section) => section.key !== "watch-outs").map((section) => section.key), [
    "what-they-do", "why-they-fit", "why-now", "how-to-approach",
  ]);
});
