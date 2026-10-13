import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { buildSync } from "esbuild";

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
    advancedTab: "page", allowIndexing: true, beginSlugEdit: noop, closeMenu: noop, copied: false,
    copyLink: noop, customHtml: "", description: "", editingSlug: false, menuOpen: true, pageUrls: {},
    previewExternally: noop, publishAsset: async () => {}, publishStatus: "draft",
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
