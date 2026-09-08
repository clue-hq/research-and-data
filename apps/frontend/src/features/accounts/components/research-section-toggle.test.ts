import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const renderer = readFileSync(new URL("./research-content.tsx", import.meta.url), "utf8");
const section = renderer.slice(renderer.indexOf("function ReadingSection("), renderer.indexOf("function ResearchTools("));
const css = readFileSync(new URL("./account-research.module.css", import.meta.url), "utf8");

test("major research headings are independent, initially closed native disclosures", () => {
  const detailsTag = section.match(/<details\b[^>]+>/)?.[0];
  assert.ok(detailsTag);
  assert.doesNotMatch(detailsTag, /\bopen\b|\bname=/);
  assert.match(section, /<summary className=\{styles\.sectionToggle\}>/);
  assert.match(section, /<h2 className=\{styles\.readingHeading\}/);
  // Ruling R9: the served `h1` is the heading; no count suffix is parsed off it.
  assert.match(section, /\{section\.h1\}/);
  assert.match(section, /section\.items\.map/);
  assert.match(section, /section\.intro\?\.map/);
  assert.doesNotMatch(renderer, /Jump to section|Menu\.Root/);
});

test("section toggles have Clue styling, visible keyboard focus and reduced-motion support", () => {
  assert.match(css, /\.sectionToggle:hover\s*\{ background: var\(--clue-background-hover\)/);
  assert.match(css, /\.sectionToggle:focus-visible/);
  assert.match(css, /\.readingSection\[open\] > \.sectionToggle \.sectionChevron/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.sectionChevron \{ transition: none;/);
});
