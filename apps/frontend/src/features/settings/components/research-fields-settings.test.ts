import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { buildSync } from "esbuild";
import type { ResearchFields } from "../model/research-fields";

// Render the actual component with its hooks; CSS modules are bundled in memory.
const bundle = buildSync({
  stdin: {
    contents: `import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { ResearchFieldsSettings } from "./research-fields-settings";
      export const render = (fields, canManage) => renderToStaticMarkup(createElement(ResearchFieldsSettings, { fields, canManage }));`,
    resolveDir: fileURLToPath(new URL(".", import.meta.url)),
  },
  bundle: true, write: false, jsx: "automatic", platform: "node", format: "cjs", packages: "external",
  outfile: "research-fields-test.cjs", logLevel: "silent",
});
const renderedModule = { exports: {} as { render: (fields: ResearchFields, canManage: boolean) => string } };
runInNewContext(bundle.outputFiles[0].text, { module: renderedModule, exports: renderedModule.exports, require: createRequire(import.meta.url) });
const fields: ResearchFields = { entity: "accounts", rows: [
  { key: "core.industry", label: "Industry", description: "Primary industry", origin: "platform", created_by: null, created_at: null },
  { key: "account.crm", label: "CRM", description: "Cite the CRM evidence", origin: "workspace", created_by: null, created_at: "2026-09-16T10:30:00Z" },
] };

test("members see real field instructions and provenance without management controls", () => {
  const html = renderedModule.exports.render(fields, false);
  assert.match(html, /Cite the CRM evidence/);
  assert.match(html, /Workspace member/);
  assert.match(html, /Sep 16, 2026/);
  assert.doesNotMatch(html, /Create field|More actions for|Edit name|Retire/);
});

test("managers can create and manage workspace fields but never platform rows", () => {
  const html = renderedModule.exports.render(fields, true);
  assert.match(html, /Create field/);
  assert.match(html, /More actions for CRM/);
  assert.doesNotMatch(html, /More actions for Industry/);
  assert.doesNotMatch(html, /Relationships|Display order|Restore defaults|AI fill|Editable by/);
});

test("an empty live registry stays empty rather than displaying dummy fields", () => {
  const html = renderedModule.exports.render({ entity: "contacts", rows: [] }, false);
  assert.match(html, /No research fields yet/);
  assert.doesNotMatch(html, /Uses Salesforce|Record id|Create field/);
});
