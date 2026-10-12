import assert from "node:assert/strict";
import { test } from "node:test";
import {
  canonicalJson,
  componentProps,
  getAtPath,
  internalRoute,
  pageFor,
  sectionDigests,
  setAtPath,
  shortcutFor,
  withAssetAt,
  withComponentProps,
  withPage,
} from "../src/editor-site";
import { SiteDocumentSchema } from "../src/site-document";
import { site } from "./fixtures/garner";

const stored = site("garner-syracuse");
const document = SiteDocumentSchema.parse({
  id: "doc_1",
  title: "Garner × Syracuse",
  theme: {},
  pages: stored.pages,
  shell: stored.shell,
  agent_sections: { AnalysisSteps: "b".repeat(64), Quote: "a".repeat(64) },
});

test("canonical JSON ignores key order and keeps array order", () => {
  assert.equal(canonicalJson({ b: 1, a: { d: [2, 1], c: null } }), canonicalJson({ a: { c: null, d: [2, 1] }, b: 1 }));
  assert.notEqual(canonicalJson({ a: [1, 2] }), canonicalJson({ a: [2, 1] }));
});

test("paths read and write nested props without mutating the original", () => {
  const props = { stats: [{ value: "7.4%", label: "x" }], slots: { headline: "Hi" } };
  assert.equal(getAtPath(props, "stats.0.value"), "7.4%");
  const next = setAtPath(props, "stats.0.value", "8%");
  assert.equal(getAtPath(next, "stats.0.value"), "8%");
  assert.equal(props.stats[0].value, "7.4%");
  assert.ok(Array.isArray(next.stats));
  assert.equal(getAtPath(setAtPath({}, "slots.headline", "New"), "slots.headline"), "New");
});

test("a page component's props are read and replaced by id, and the id is kept", () => {
  assert.equal(componentProps(document, "/", "proof")?.heading, "7.4% lower medical spend in year one. No plan changes.");
  const edited = withComponentProps(document, "/", "proof", { heading: "Edited", id: "something-else" });
  assert.equal(componentProps(edited, "/", "proof")?.heading, "Edited");
  assert.equal(componentProps(edited, "/", "proof")?.id, "proof");
  assert.equal(withComponentProps(document, "/", "missing", { heading: "x" }), document, "an unknown id changes nothing");
});

test("the header and footer are addressed through the shell target", () => {
  assert.equal(componentProps(document, "shell", "header")?.preparedFor, "Syracuse City School District");
  const edited = withComponentProps(document, "shell", "footer", { legal: "© 2027" });
  assert.equal(componentProps(edited, "shell", "footer")?.legal, "© 2027");
  assert.equal(componentProps(edited, "shell", "footer")?.id, "footer");
  assert.equal(componentProps(document, "shell", "sidebar"), null);
});

test("an asset lands at its prop path", () => {
  const url = `/asset-store/${"d".repeat(64)}`;
  const edited = withAssetAt(document, "/analysis", "what", "image", url);
  assert.equal(componentProps(edited, "/analysis", "what")?.image, url);
});

test("internal links resolve only to pages the site has", () => {
  assert.equal(internalRoute("/analysis", document), "/analysis");
  assert.equal(internalRoute("/analysis/", document), "/analysis");
  assert.equal(internalRoute("/analysis#top", document), "/analysis");
  assert.equal(internalRoute("/", document), "/");
  assert.equal(internalRoute("/pricing", document), null);
  assert.equal(internalRoute("https://garnerhealth.com/", document), null);
  assert.equal(internalRoute("//evil.example/", document), null);
});

test("withPage replaces one page; pageFor reads only the site's own routes", () => {
  const page = { root: { props: { title: "New" } }, content: [] };
  assert.equal(pageFor(withPage(document, "/analysis", page), "/analysis")?.root.props.title, "New");
  assert.equal(pageFor(document, "toString"), null);
});

test("section digests are the sorted digests of the site's agent sections", () => {
  assert.deepEqual(sectionDigests(document), ["a".repeat(64), "b".repeat(64)]);
});

test("⌘Z, ⇧⌘Z and Ctrl+Y become undo and redo, but never while typing", () => {
  const key = (value: string, extra: Partial<{ metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; target: unknown }> = {}) => ({
    ctrlKey: false,
    key: value,
    metaKey: false,
    shiftKey: false,
    target: { tagName: "DIV" },
    ...extra,
  });
  assert.equal(shortcutFor(key("z", { metaKey: true })), "undo");
  assert.equal(shortcutFor(key("Z", { metaKey: true, shiftKey: true })), "redo");
  assert.equal(shortcutFor(key("y", { ctrlKey: true })), "redo");
  assert.equal(shortcutFor(key("i", { metaKey: true })), "swallow");
  assert.equal(shortcutFor(key("z")), null);
  assert.equal(shortcutFor(key("z", { metaKey: true, target: { isContentEditable: true } })), null);
  assert.equal(shortcutFor(key("z", { ctrlKey: true, target: { tagName: "INPUT" } })), null);
});
