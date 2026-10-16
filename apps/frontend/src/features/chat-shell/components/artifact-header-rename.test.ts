import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { buildSync } from "esbuild";
import { AGENT_RUN_LOCK_NOTE } from "../model/agent-run-lock";

// K1-5 (founder ruling 2026-10-16): renaming a document is not allowed while a design run drives
// it. The header's Rename is inert under the agent-run lock and says why; a rename the server
// refused anyway (a run that started first) shows the same sentence beside the title.
const bundle = buildSync({
  stdin: {
    contents: `import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { ArtifactActionMenu } from "./artifact-action-menu";
      import { ArtifactHeader } from "./artifact-header";
      export const renderMenu = (props) => renderToStaticMarkup(createElement(ArtifactActionMenu, props));
      export const renderHeader = (props) => renderToStaticMarkup(createElement(ArtifactHeader, props));`,
    resolveDir: fileURLToPath(new URL(".", import.meta.url)),
  },
  bundle: true, write: false, jsx: "automatic", platform: "node", format: "cjs", packages: "external",
  outfile: "artifact-header-rename-test.cjs", logLevel: "silent",
});
type Render = (props: Record<string, unknown>) => string;
const renderedModule = { exports: {} as { renderMenu: Render; renderHeader: Render } };
runInNewContext(bundle.outputFiles[0].text, {
  module: renderedModule, exports: renderedModule.exports, require: createRequire(import.meta.url), URL,
});

const noop = () => {};
const menuProps = (overrides: Record<string, unknown> = {}) => ({
  onRename: noop, onRequestAction: noop, onSelectVersion: noop, onVersionsOpenChange: noop,
  selectedVersionId: "current", versionsOpen: false, ...overrides,
});
const RENAME_BUTTON = /<button[^>]*>(?:(?!<\/button>).)*<span>Rename<\/span><\/button>/;

test("while the agent works the Rename item is disabled and the lock's sentence sits under it", () => {
  const html = renderedModule.exports.renderMenu(menuProps({ renameLockNote: AGENT_RUN_LOCK_NOTE }));
  const button = html.match(RENAME_BUTTON)?.[0] ?? "";
  assert.match(button, /disabled=""/);
  const after = html.slice(html.indexOf(button) + button.length);
  assert.match(after, /^<p[^>]*>The design agent is working — editing unlocks when it finishes\.<\/p>/);
});

test("with no run the Rename item is live and says nothing", () => {
  const html = renderedModule.exports.renderMenu(menuProps());
  const button = html.match(RENAME_BUTTON)?.[0] ?? "";
  assert.ok(button);
  assert.doesNotMatch(button, /disabled/);
  assert.doesNotMatch(html, /design agent is working/);
});

const headerProps = (overrides: Record<string, unknown> = {}) => ({
  editing: false, kind: "site", onEdit: noop, onRename: noop, title: "Garner for Syracuse", ...overrides,
});

test("a rename the server refused shows the lock's sentence beside the unchanged title", () => {
  const html = renderedModule.exports.renderHeader(headerProps({ renameNote: AGENT_RUN_LOCK_NOTE }));
  assert.match(html, /Garner for Syracuse/);
  assert.match(html, /<p[^>]*role="status"[^>]*>The design agent is working — editing unlocks when it finishes\.<\/p>/);
});

test("with no refusal the header carries no rename note", () => {
  const html = renderedModule.exports.renderHeader(headerProps());
  assert.doesNotMatch(html, /design agent is working/);
});
