import assert from "node:assert/strict";
import { test } from "node:test";
import {
  BrandDataSchema,
  SectionLinkSchema,
  SiteDocumentSchema,
  SiteTargetSchema,
} from "../src/site-document";
import { garner, site } from "./fixtures/garner";

const stored = site("garner-syracuse");
const document = {
  id: "doc_1",
  title: "Garner × Syracuse",
  theme: {},
  pages: stored.pages,
  shell: stored.shell,
  agent_sections: {},
};

test("the garner fixture site is a Contract 1 site document", () => {
  const parsed = SiteDocumentSchema.parse(document);
  assert.deepEqual(Object.keys(parsed.pages), ["/", "/analysis"]);
});

test("the born-empty site (the Wave 1 minter's shape) parses", () => {
  const parsed = SiteDocumentSchema.parse({
    id: "doc_2",
    title: "New site",
    theme: {},
    pages: { "/": { root: { props: { title: "New site" } }, content: [] } },
    shell: null,
    agent_sections: {},
  });
  assert.equal(parsed.shell, null);
});

test("a site without a home page, with a bad route or an unsafe component id is refused", () => {
  assert.equal(
    SiteDocumentSchema.safeParse({ ...document, pages: { "/analysis": stored.pages["/analysis"] } }).success,
    false,
  );
  assert.equal(
    SiteDocumentSchema.safeParse({ ...document, pages: { ...document.pages, "/Bad Route": stored.pages["/"] } }).success,
    false,
  );
  const page = { root: { props: {} }, content: [{ type: "CtaBand", props: { id: "cta#1" } }] };
  assert.equal(SiteDocumentSchema.safeParse({ ...document, pages: { "/": page } }).success, false);
});

test("agent sections map PascalCase names to sha256 digests", () => {
  const digest = "a".repeat(64);
  assert.equal(SiteDocumentSchema.safeParse({ ...document, agent_sections: { AnalysisSteps: digest } }).success, true);
  assert.equal(SiteDocumentSchema.safeParse({ ...document, agent_sections: { analysis: digest } }).success, false);
  assert.equal(SiteDocumentSchema.safeParse({ ...document, agent_sections: { AnalysisSteps: "short" } }).success, false);
});

test("a target is a page route or the shell", () => {
  for (const ok of ["/", "/analysis", "shell"]) assert.equal(SiteTargetSchema.safeParse(ok).success, true, ok);
  for (const bad of ["", "analysis", "/a/b", "SHELL"]) assert.equal(SiteTargetSchema.safeParse(bad).success, false, bad);
});

test("the fixture brand parses and a section link needs a real token", () => {
  assert.equal(BrandDataSchema.parse(garner()).slug, "garner");
  const link = { name: "AnalysisSteps", digest: "b".repeat(64), propsSchema: { type: "object" } };
  assert.equal(SectionLinkSchema.safeParse({ ...link, token: "short" }).success, false);
  assert.equal(SectionLinkSchema.safeParse({ ...link, token: "tok_0123456789abcdef" }).success, true);
});

test("a brand from an older server that still sends measured parses", () => {
  assert.equal(BrandDataSchema.safeParse({ ...garner(), measured: null }).success, true);
});
