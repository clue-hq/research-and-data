import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { it } from "node:test";
import { fileURLToPath } from "node:url";
import type { Scene } from "../engine/scene/contracts";
import { AD_PAGE_ID, HARVESTED_AD_PAGE } from "./__fixtures__/scene-nodes";
import {
  PAGELESS_SCENE_NOTICE,
  effectiveScenePageId,
  isPagelessScene,
  scenePagelessNotice,
} from "./scene-pageless";

/**
 * genad2 Task 5 — the zero-page lifecycle.
 *
 * The platform now births a scene (ad) document with NO page at all
 * (`open_design_leg@4`): the document exists, the artifact card exists, the tab
 * auto-opens, and `pages` stays `{}` until the design agent authors the first
 * page in a later turn. Every assertion below is about that window.
 */

/** The newborn shape: real meta, `pages: {}`, and nothing else authored yet. */
const PAGELESS_SCENE: Scene = {
  ...HARVESTED_AD_PAGE,
  assets: {},
  nodes: {},
  pages: {},
};

it("a scene with no pages is pageless; the harvested ad is not", () => {
  assert.equal(isPagelessScene(PAGELESS_SCENE), true);
  assert.equal(isPagelessScene(HARVESTED_AD_PAGE), false);
});

it("the pageless notice is the ratified copy, verbatim", () => {
  // Task-5 contract (a). The wording is the founder's, not this lane's — pinned
  // here so a reword is a deliberate edit to a test, never a drift.
  assert.equal(
    PAGELESS_SCENE_NOTICE,
    "Design hasn't created the page yet — it will appear when generation completes. Send a message to start (or retry).",
  );
});

it("the pageless notice shows for a loaded zero-page scene", () => {
  assert.equal(scenePagelessNotice(PAGELESS_SCENE, null), PAGELESS_SCENE_NOTICE);
});

it("a loading document says nothing at all", () => {
  // Null scene is "not loaded yet", which is NOT the same fact as "the agent has
  // not authored a page". Claiming the second while the first is true would be a
  // fabrication of its own — the stage stays silent until the document answers.
  assert.equal(scenePagelessNotice(null, null), null);
});

it("a page-bearing document never shows the notice", () => {
  assert.equal(scenePagelessNotice(HARVESTED_AD_PAGE, AD_PAGE_ID), null);
  // Defensive: a page-bearing scene whose page id has not resolved yet is still
  // not pageless, so it earns no notice either.
  assert.equal(scenePagelessNotice(HARVESTED_AD_PAGE, null), null);
});

/**
 * Task-5 contract (b): the un-hydrated ad inspector's canvas schema fabricates
 * `1200`/`1200` and a `Linkedin square` preset out of `DEFAULT_STATE` — values
 * a pageless document does not have. The panel is a `.tsx` and cannot be
 * imported under this runner (`tsx --test`, no DOM), so the placement of the
 * refusal is pinned against the source literal — the same technique
 * `scene-hydrate.test.ts` and `scene-engine-banners.test.ts` already use.
 */
const AD_INSPECTOR_SOURCE = readFileSync(
  join(
    dirname(fileURLToPath(import.meta.url)),
    "..",
    "..",
    "chat-shell",
    "components",
    "image-inspector.tsx",
  ),
  "utf8",
);

it("the ad canvas schema refuses its page rows BEFORE it can render them", () => {
  const schema = AD_INSPECTOR_SOURCE.indexOf("function AdCanvasInspector");
  assert.notEqual(schema, -1, "AdCanvasInspector moved");
  const body = AD_INSPECTOR_SOURCE.slice(schema);
  const refusal = body.indexOf("if (pageless)");
  // The Size select and the Custom W/H boxes — the exact rows that would show
  // `DEFAULT_STATE`'s invented 1200x1200 over a document with no page.
  const sizeRows = body.indexOf('ariaLabel="Custom width"');
  assert.notEqual(refusal, -1, "AdCanvasInspector must have a pageless branch");
  assert.notEqual(sizeRows, -1, "the canvas Custom-size rows moved");
  assert.ok(
    refusal < sizeRows,
    "the pageless branch must return before the Size/Custom-size rows",
  );
  // And the placeholder is the one ratified sentence, not a second wording.
  assert.ok(AD_INSPECTOR_SOURCE.includes("PAGELESS_SCENE_NOTICE"));
});

/**
 * genad2 Task 7 (close-out sweep): the FOUR-HOP forward that carries the fact.
 *
 * `pageless` is computed once (`use-scene-editing-session.ts`) and then handed
 * down: both mounts → `ImageInspector` → `AdCanvasInspector`. The refusal
 * pinned above is inert if any hop is dropped, and dropping one is SILENT —
 * `pageless` defaults to `false` at every prop site, so the panel quietly goes
 * back to fabricating `1200`x`1200` over a document with no page. These are
 * `.tsx` and cannot be imported under this runner, so the wiring is pinned the
 * same source-literal way as the refusal itself.
 */
const chatShellSource = (file: string): string =>
  readFileSync(
    join(
      dirname(fileURLToPath(import.meta.url)),
      "..",
      "..",
      "chat-shell",
      "components",
      file,
    ),
    "utf8",
  );

it("both mounts forward the session's pageless fact to the inspector", () => {
  for (const file of ["chat-surface.tsx", "editor-surface.tsx"]) {
    assert.ok(
      chatShellSource(file).includes("pageless={sceneSession.pageless}"),
      `${file} must forward sceneSession.pageless to the inspector`,
    );
  }
});

it("the inspector forwards pageless to EVERY AdCanvasInspector it renders", () => {
  const renders = AD_INSPECTOR_SOURCE.split("<AdCanvasInspector").length - 1;
  assert.ok(renders > 0, "AdCanvasInspector render sites moved");
  assert.equal(
    AD_INSPECTOR_SOURCE.split("<AdCanvasInspector pageless={pageless}").length - 1,
    renders,
    "every AdCanvasInspector render must pass pageless, or the refusal is inert",
  );
});

it("Plan 2 item D: a pageless load takes its page from the scene being drawn", () => {
  // The document loaded with `pages: {}` (pageId null). The reveal pump then
  // applied a streamed `add_page`, so the DRAWN scene has a page. The canvas
  // must draw that page now, not after the next checkpoint reload.
  assert.equal(effectiveScenePageId(null, HARVESTED_AD_PAGE), AD_PAGE_ID);
});

it("a loaded page id wins over the drawn scene", () => {
  assert.equal(effectiveScenePageId(AD_PAGE_ID, PAGELESS_SCENE), AD_PAGE_ID);
  assert.equal(effectiveScenePageId(AD_PAGE_ID, HARVESTED_AD_PAGE), AD_PAGE_ID);
});

it("nothing drawn and nothing loaded is still no page", () => {
  assert.equal(effectiveScenePageId(null, null), null);
  assert.equal(effectiveScenePageId(null, PAGELESS_SCENE), null);
});

it("the pageless notice clears the moment the drawn scene has a page", () => {
  const drawn = HARVESTED_AD_PAGE;
  const pageId = effectiveScenePageId(null, drawn);
  assert.equal(scenePagelessNotice(drawn, pageId), null);
  // …and still shows while the drawn scene is pageless.
  assert.equal(
    scenePagelessNotice(PAGELESS_SCENE, effectiveScenePageId(null, PAGELESS_SCENE)),
    PAGELESS_SCENE_NOTICE,
  );
});
