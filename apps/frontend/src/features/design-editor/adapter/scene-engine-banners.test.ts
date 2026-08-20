import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { it } from "node:test";
import type { SceneEngineStatus } from "../hooks/use-scene-document";
import { sceneEngineBanners } from "./scene-engine-banners";

/**
 * Gate G-D: the engine-forced banners say what the MVP editor's banners say.
 *
 * The founder ruled the copy "as is from the MVP editor", so the load-bearing
 * assertion here is not that the strings read well — it is that they are the
 * upstream strings. Every sentence is checked against the actual source file,
 * so a future edit to either side fails loudly instead of quietly forking the
 * two editors' voices.
 */

const ACTIVE: SceneEngineStatus = {
  engineDisabled: false,
  reason: null,
  detail: null,
};

function disabled(
  reason: SceneEngineStatus["reason"],
  detail: string | null,
): SceneEngineStatus {
  return { engineDisabled: true, reason, detail };
}

const UPSTREAM_CHROME = readFileSync(
  join(
    dirname(fileURLToPath(import.meta.url)),
    "../../../../../..",
    "subsystems/clue-design/apps/editor/src/components/EditorChrome.tsx",
  ),
  "utf8",
);

it("says nothing when the engine is live and Skia is measuring", () => {
  assert.deepEqual(sceneEngineBanners(ACTIVE, "skia"), []);
});

it("names the stamp mismatch, and goes read-only in the same voice as the MVP editor", () => {
  const [banner, ...rest] = sceneEngineBanners(
    disabled("version_mismatch", "editor engine 7b992f8c6ec8 vs API engine 4a10c9d3e771"),
    "skia",
  );
  assert.equal(rest.length, 0);
  assert.equal(banner.kind, "engine-disabled");
  assert.equal(banner.title, "Canvas editing is disabled");
  assert.match(banner.body, /^The in-browser engine is a different build than the API\./);
  assert.match(banner.body, /Rebuild it to match, then hard-refresh \(⌘⇧R\):$/);
  // The two hashes are the whole point of the state: they ride through verbatim.
  assert.equal(banner.detail, "editor engine 7b992f8c6ec8 vs API engine 4a10c9d3e771");
});

it("distinguishes the three engine reasons the handshake can report", () => {
  const headline = (reason: SceneEngineStatus["reason"]) =>
    sceneEngineBanners(disabled(reason, "detail"), "skia")[0].body;

  assert.match(headline("handshake_failed"), /^Couldn’t verify the in-browser engine against the API\./);
  assert.match(headline("load_failed"), /^The in-browser engine failed to load\./);
  // A null reason cannot happen while `engineDisabled` is true, but the copy
  // must never come out blank if it ever did.
  assert.match(headline(null), /^The in-browser engine failed to load\./);
});

it("warns that degraded measurement is a rendering difference, not a crash", () => {
  const [banner, ...rest] = sceneEngineBanners(ACTIVE, "heuristic");
  assert.equal(rest.length, 0);
  assert.equal(banner.kind, "heuristic-measurement");
  assert.equal(banner.title, "Text measurement degraded");
  assert.match(banner.body, /may misfit or not appear as it will on export/);
  assert.equal(banner.detail, null);
});

it("stacks both banners when both failures are live (upstream would overlap them)", () => {
  const banners = sceneEngineBanners(
    disabled("handshake_failed", "the API build-info request failed: Failed to fetch"),
    "heuristic",
  );
  assert.deepEqual(
    banners.map((banner) => banner.kind),
    ["engine-disabled", "heuristic-measurement"],
  );
});

it("carries the MVP editor's exact sentences, not a paraphrase of them", () => {
  const sentences = [
    "Canvas editing is disabled",
    "The in-browser engine is a different build than the API.",
    "Couldn’t verify the in-browser engine against the API.",
    "The in-browser engine failed to load.",
    "Rebuild it to match, then hard-refresh (⌘⇧R):",
    "Start the API, rebuild the engine, then hard-refresh (⌘⇧R):",
    "Build it, then hard-refresh (⌘⇧R):",
    "Text measurement degraded",
  ];
  for (const sentence of sentences) {
    assert.ok(
      UPSTREAM_CHROME.includes(sentence),
      `not upstream copy: ${sentence}`,
    );
  }

  // The two long bodies are assembled from upstream fragments, so they are
  // checked fragment-wise against the same file.
  const body = sceneEngineBanners(disabled("load_failed", null), "skia")[0].body;
  assert.ok(
    UPSTREAM_CHROME.includes(
      "You can’t select or edit anything on the canvas until the in-browser",
    ) && body.includes(
      "You can’t select or edit anything on the canvas until the in-browser engine is running.",
    ),
  );

  const heuristicBody = sceneEngineBanners(ACTIVE, "heuristic")[0].body;
  for (const fragment of [
    "Canvas geometry is approximate (font engine unavailable). On-canvas text is laid out with",
    "a heuristic estimate and may misfit or not appear as it will on export. Reload the editor;",
    "if it persists, rebuild the CanvasKit and font assets, then hard-refresh (⌘⇧R).",
  ]) {
    assert.ok(UPSTREAM_CHROME.includes(fragment), `not upstream copy: ${fragment}`);
    // The upstream string is JSX-wrapped across lines; ours is one sentence.
    assert.ok(heuristicBody.includes(fragment.replace(/\s+/g, " ").trim()));
  }
});

it("names a command that exists in THIS repo (the one deviation, disclosed)", () => {
  const engine = sceneEngineBanners(disabled("version_mismatch", "d"), "skia")[0];
  const assets = sceneEngineBanners(ACTIVE, "heuristic")[0];

  const vendorScript = readFileSync(
    join(
      dirname(fileURLToPath(import.meta.url)),
      "../../../..",
      "scripts/copy-design-vendor.mjs",
    ),
    "utf8",
  );
  // Our own vendor script prints the wasm remedy; the banner must not invent a
  // different one.
  assert.ok(vendorScript.includes(engine.command));
  assert.equal(assets.command, "node scripts/copy-design-vendor.mjs");
  // And neither may be the upstream command, which does not exist here.
  assert.notEqual(engine.command, "npm run build:wasm");
});
