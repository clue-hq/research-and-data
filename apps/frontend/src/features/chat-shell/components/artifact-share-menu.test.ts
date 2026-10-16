import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { buildSync } from "esbuild";
import { AGENT_RUN_PUBLISH_NOTE } from "../model/agent-run-lock";

// Founder ruling 2026-10-13: a website (web or site) has no ZIP or PDF download —
// hosting on the platform is the only delivery. Render the real menu (CSS modules
// bundled in memory) over the controller state it reads, and read its markup.
const bundle = buildSync({
  stdin: {
    contents: `import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { ArtifactShareMenu } from "./artifact-share-menu";
      export const render = (controller) => renderToStaticMarkup(createElement(ArtifactShareMenu, { controller }));`,
    resolveDir: fileURLToPath(new URL(".", import.meta.url)),
  },
  bundle: true, write: false, jsx: "automatic", platform: "node", format: "cjs", packages: "external",
  outfile: "artifact-share-menu-test.cjs", logLevel: "silent",
});
const renderedModule = { exports: {} as { render: (controller: Record<string, unknown>) => string } };
runInNewContext(bundle.outputFiles[0].text, { module: renderedModule, exports: renderedModule.exports, require: createRequire(import.meta.url), URL });

const noop = () => {};

/** The share menu's controller as a website artifact's share button hands it over. */
function websiteController(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    advancedTab: "page", allowIndexing: true, beginSlugEdit: noop, changesSincePublish: false, closeMenu: noop, copied: false,
    copyLink: noop, customHtml: "", description: "", editingSlug: false, menuOpen: true, pageUrls: {},
    previewExternally: noop, publishAsset: async () => {}, publishFailureNote: null, publishLocked: false, publishLockNote: null,
    publishStatus: "draft",
    regenerateDescriptionOnPublish: false, requestDescriptionGeneration: noop, saveAdvancedSettings: noop,
    saveSlug: noop, setAdvancedTab: noop, setAllowIndexing: noop, setCustomHtml: noop, setDescription: noop,
    setRegenerateDescriptionOnPublish: noop, setShareTitle: noop, setSlugDraft: noop, setView: noop,
    shareHost: "", shareTitle: "Spring launch", shareUrl: "", slug: "spring-launch", slugDirty: false,
    slugDraft: "spring-launch", statusMessage: "", toggleMenu: noop, view: "main",
    ...overrides,
  };
}

test("an unpublished website's share menu offers publishing and no download", () => {
  const html = renderedModule.exports.render(websiteController());
  assert.match(html, /Publish asset/);
  assert.match(html, /Advanced publishing settings/);
  assert.doesNotMatch(html, /Export|ZIP|PDF/);
});

test("a published website's share menu offers its link and no download", () => {
  const html = renderedModule.exports.render(websiteController({
    publishStatus: "published",
    shareHost: "acme.pages.cluehq.ai",
    shareUrl: "https://acme.pages.cluehq.ai/spring-launch",
  }));
  assert.match(html, /Asset published/);
  assert.match(html, /Copy link/);
  assert.match(html, /Preview externally/);
  assert.doesNotMatch(html, /Export|ZIP|PDF/);
});

// Task 28 (founder 2026-10-13): while the design agent works on the page, Publish is inert and the
// founder's sentence sits directly under it.

const PUBLISH_BUTTON = /<button[^>]*>Publish asset<\/button>/;

test("while the agent works the Publish button is disabled and the note sits right under it", () => {
  const html = renderedModule.exports.render(websiteController({
    publishLocked: true,
    publishLockNote: AGENT_RUN_PUBLISH_NOTE,
  }));
  const button = html.match(PUBLISH_BUTTON)?.[0] ?? "";
  assert.match(button, /disabled=""/);
  const after = html.slice(html.indexOf(button) + button.length);
  assert.match(after, /^<p[^>]*>The design agent is working — publishing unlocks when it finishes\.<\/p>/);
});

test("a refused publish (a run that started after the menu opened) shows the same note, button live", () => {
  const html = renderedModule.exports.render(websiteController({
    publishLocked: false,
    publishLockNote: AGENT_RUN_PUBLISH_NOTE,
  }));
  const button = html.match(PUBLISH_BUTTON)?.[0] ?? "";
  assert.doesNotMatch(button, /disabled/);
  assert.equal(html.split(AGENT_RUN_PUBLISH_NOTE).length - 1, 1);
  assert.doesNotMatch(html, /agent_run_active/);
});

test("with no run in the way the Publish button is live and there is no note", () => {
  const html = renderedModule.exports.render(websiteController());
  const button = html.match(PUBLISH_BUTTON)?.[0] ?? "";
  assert.doesNotMatch(button, /disabled/);
  assert.doesNotMatch(html, /design agent is working/);
});

// K6-2: a site changed since it was published says so and offers Republish.

const PUBLISHED = {
  publishStatus: "published",
  shareHost: "acme.pages.cluehq.ai",
  shareUrl: "https://acme.pages.cluehq.ai/spring-launch",
};

test("a published site changed since its publish says so and offers Republish", () => {
  const html = renderedModule.exports.render(websiteController({ ...PUBLISHED, changesSincePublish: true }));
  assert.match(html, /Changes since you published/);
  assert.match(html, /<button[^>]*>Republish<\/button>/);
  assert.doesNotMatch(html, /Asset published/);
});

test("a published site with no changes shows the published state, with no Republish", () => {
  const html = renderedModule.exports.render(websiteController(PUBLISHED));
  assert.match(html, /Asset published/);
  assert.doesNotMatch(html, /Changes since you published|Republish/);
});

test("a publish stopped by an unsaved edit says why right under the button", () => {
  const note = "Not published: your latest edit was not saved (Failed to fetch).";
  const html = renderedModule.exports.render(websiteController({ publishFailureNote: note }));
  const button = html.match(PUBLISH_BUTTON)?.[0] ?? "";
  const after = html.slice(html.indexOf(button) + button.length);
  assert.ok(after.startsWith(`<p class="`) && after.includes(note), after.slice(0, 200));
});
