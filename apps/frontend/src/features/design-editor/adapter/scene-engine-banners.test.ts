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

it("states a missing pinned-kit face and the deterministic fallback explicitly", () => {
  const banners = sceneEngineBanners(ACTIVE, "skia", [
    {
      severity: "warning",
      phase: "brand",
      code: "EDITOR_KIT_FONT_FAMILY_UNAVAILABLE",
      message:
        "Brand Kit declares “sohne-var” but supplies no TTF/OTF face assets; canvas and server export use the deterministic Inter fallback.",
      subject: { kind: "document" },
      hint: "Ingest licensed TTF/OTF files for “sohne-var” to render that family.",
    },
  ]);

  assert.equal(banners.length, 1);
  assert.equal(banners[0].kind, "font-fallback");
  assert.equal(banners[0].title, "Brand font unavailable");
  assert.match(banners[0].body, /sohne-var/);
  assert.match(banners[0].body, /canvas and server export/);
  assert.equal(banners[0].command, "Deterministic fallback: Inter");
  assert.match(banners[0].detail ?? "", /licensed TTF\/OTF/);
});

it("leads the font banner with an error-severity diagnostic over an earlier warning", () => {
  // The array concatenates kit before library diagnostics; the banner must
  // still be led by the worst one, not the first one.
  const banners = sceneEngineBanners(ACTIVE, "skia", [
    {
      severity: "warning",
      phase: "brand",
      code: "EDITOR_KIT_FONT_FAMILY_UNAVAILABLE",
      message: "Brand Kit declares “sohne-var” but supplies no TTF/OTF face assets.",
      subject: { kind: "document" },
      hint: "Ingest licensed TTF/OTF files.",
    },
    {
      severity: "error",
      phase: "brand",
      code: "EDITOR_PINNED_BRAND_KIT_UNAVAILABLE",
      message:
        "Pinned Brand Kit brand_acme@6 could not be loaded (HTTP 404); canvas uses deterministic fallback tokens and Inter rather than a different kit version.",
      subject: { kind: "document" },
      hint: "Restore that exact Brand Kit version.",
    },
  ]);

  assert.equal(banners.length, 1);
  assert.equal(banners[0].title, "Pinned Brand Kit unavailable");
  assert.match(banners[0].body, /brand_acme@6/);
  assert.match(banners[0].body, /1 additional font diagnostic reported\./);
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

it("names unresolved layout even when the font shaper is available", () => {
  const [banner] = sceneEngineBanners(ACTIVE, "unsettled");
  assert.equal(banner.title, "Text layout needs verification");
  assert.match(banner.body, /could not confirm every text measurement/);
});

it("keeps blocking failures critical and advisory rendering issues as warnings", () => {
  assert.equal(sceneEngineBanners(disabled("load_failed", null), "skia")[0].severity, "error");
  assert.equal(sceneEngineBanners(ACTIVE, "heuristic")[0].severity, "warning");
  assert.equal(sceneEngineBanners(ACTIVE, "unsettled")[0].severity, "warning");

  for (const severity of ["warning", "error"] as const) {
    const diagnostic = {
      severity, phase: "brand" as const, code: "FONT_UNAVAILABLE",
      message: "A font is unavailable.", subject: { kind: "document" as const }, hint: null,
    };
    assert.equal(sceneEngineBanners(ACTIVE, "skia", [diagnostic])[0].severity, severity);
    assert.equal(sceneEngineBanners(ACTIVE, "skia", [], {
      status: "ready", diagnostics: [diagnostic],
    })[0].severity, severity);
  }

  // A blocked canvas remains critical even before a diagnostic arrives.
  assert.equal(sceneEngineBanners(ACTIVE, "skia", [], {
    status: "invalid", diagnostics: [],
  })[0].severity, "error");
});

it("classifies blocked render context separately from fonts and does not claim a rendered fallback", () => {
  const banners = sceneEngineBanners(ACTIVE, "heuristic", [{
    severity: "warning", phase: "brand", code: "EDITOR_KIT_FONT_FAMILY_UNAVAILABLE",
    message: "A font asset is unavailable.", subject: { kind: "document" }, hint: null,
  }], { status: "invalid", diagnostics: [{
    severity: "error", phase: "brand", code: "EDITOR_RENDER_MODE_UNSUPPORTED",
    message: "Brand Kit does not declare mode theme.unknown", hint: "Select a supported theme.",
    subject: { kind: "document" },
  }] });
  assert.equal(banners.length, 1);
  assert.equal(banners[0].kind, "render-context");
  assert.equal(banners[0].title, "Canvas rendering unavailable");
  assert.match(banners[0].body, /theme\.unknown/);
  assert.equal(banners[0].detail, "Select a supported theme.");
  assert.doesNotMatch(JSON.stringify(banners), /Inter|font unavailable|geometry is approximate/);
});
