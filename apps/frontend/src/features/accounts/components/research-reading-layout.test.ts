import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { researchSources } from "../model/research-presentation";
import { zafranWorkspaceFixture } from "../data/zafran/insights";
import { nickFisherFixture } from "../data/zafran/contacts";

const renderer = readFileSync(new URL("./research-content.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("./account-research.module.css", import.meta.url), "utf8");

test("research pages retain every section and item without tabs or priority truncation", () => {
  const reading = renderer.slice(renderer.indexOf("function ReadingSection("), renderer.indexOf("export function ResearchOverview("));
  assert.match(reading, /section\.items\.map/);
  assert.match(reading, /sections\.filter\(\(section\) => !section\.restricted\)\.map/);
  assert.match(reading, /displaySections\.filter\(\(section\) => !section\.restricted\)\.map/);
  assert.doesNotMatch(reading, /role="tab|activeSection|prioritizedItems|\.slice\(/);
  assert.doesNotMatch(reading, /Jump to section/);
});

test("sources and retained internal notes are accessible above the research on both pages", () => {
  for (const name of ["ResearchDocument", "ResearchStack"]) {
    const start = renderer.indexOf(`export function ${name}(`);
    const next = renderer.indexOf("export function", start + 1);
    const component = renderer.slice(start, next);
    assert.ok(component.indexOf("<ResearchTools") < component.indexOf("<ReadingSection"));
  }
  assert.match(renderer, /aria-label="Sources"/);
  assert.match(renderer, /hidden=\{panel !== "notes"\}/);
  assert.match(renderer, /notes\.map\(\(section\)/);
  assert.doesNotMatch(renderer, /<summary>Sources|"Context only"/);
});

test("the reading surface has neither priority rails nor repeated boxed copy lines", () => {
  assert.doesNotMatch(css, /border-left:/);
  assert.match(css, /\.readingDocument \.sendLine\s*\{\s*background: none;\s*border: 0;/);
  assert.match(renderer, /!reading && unmentionedContacts\.length/);
});

test("source access retains the cited account URLs and only relevant contact URLs", () => {
  // No `register-` admission any more (source map §6): a source is listed
  // because the page cites its claim, not because of how its id is spelled.
  const sources = researchSources(zafranWorkspaceFixture.insightsDisplay!.sections, zafranWorkspaceFixture.researchEvidence);
  assert.equal(new Set(sources.map((source) => source.sourceUrl)).size, sources.length);
  assert.ok(sources.length > 0);
  const contactSources = researchSources(nickFisherFixture.contactDisplay!.sections, nickFisherFixture.researchEvidence);
  assert.equal(contactSources.length, 14);
  assert.ok(contactSources.some((source) => source.sourceDomain === "youtube.com"));
  assert.ok(contactSources.some((source) => source.sourceDomain === "globes.co.il"), "Internal-note sources remain available");
});
