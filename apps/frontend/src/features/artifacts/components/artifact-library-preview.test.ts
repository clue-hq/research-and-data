import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { test } from "node:test";
import { buildSync } from "esbuild";

// Founder ruling 2026-10-13: a web page or site has no download in the gallery —
// publishing is its only delivery — while an ad keeps its image export. Render the
// real preview dialog (CSS modules bundled in memory) over a library row of each kind.
const bundle = buildSync({
  stdin: {
    contents: `import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { ArtifactLibraryPreview } from "./artifact-library-preview";
      import { ArtifactWireSchema, toLibraryArtifact } from "../model/artifact-library";
      export const render = (row, actions) => renderToStaticMarkup(createElement(ArtifactLibraryPreview, {
        actions,
        artifact: toLibraryArtifact(ArtifactWireSchema.parse(row), new Date("2026-10-13T12:00:00Z")),
        onClose: () => {},
      }));`,
    resolveDir: fileURLToPath(new URL(".", import.meta.url)),
  },
  bundle: true, write: false, jsx: "automatic", platform: "node", format: "cjs", packages: "external",
  outfile: "artifact-library-preview-test.cjs", logLevel: "silent",
});
const renderedModule = { exports: {} as { render: (row: Record<string, unknown>, actions: Record<string, unknown>) => string } };
runInNewContext(bundle.outputFiles[0].text, { module: renderedModule, exports: renderedModule.exports, require: createRequire(import.meta.url), URL, URLSearchParams });

const actions = {
  busy: false, notice: "", dismissNotice: () => {}, save: async () => true, archive: async () => true,
  rename: async () => true, exportAd: async () => {}, viewed: () => {}, openEditor: async () => {},
};

function row(kind: "web" | "site" | "ad"): Record<string, unknown> {
  return {
    id: `art-${kind}`, document_id: `doc-${kind}`, project_id: "prj-1", project_title: "Syracuse ABM",
    kind, title: "Spring launch", status: "draft", current_version: 3,
    created_at: "2026-10-11T09:00:00+00:00", updated_at: "2026-10-11T10:00:00+00:00",
    origin_thread_id: "thread-1", artifact_type: kind === "ad" ? "linkedin_single_image" : null,
    width_px: kind === "ad" ? 1200 : null, height_px: kind === "ad" ? 627 : null,
    account: null, archived_at: null, saved: false, last_viewed_at: null,
  };
}

for (const kind of ["web", "site"] as const) {
  test(`a ${kind} artifact's gallery preview offers no download`, () => {
    const html = renderedModule.exports.render(row(kind), actions);
    assert.match(html, /Copy artifact link/);
    assert.doesNotMatch(html, /Export|Download|ZIP|PDF|Original image/);
  });
}

test("an ad artifact's gallery preview keeps its image download", () => {
  const html = renderedModule.exports.render(row("ad"), actions);
  assert.match(html, /Download preview/);
  assert.match(html, /Original image/);
});
