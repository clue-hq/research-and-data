import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import type { Node, Scene } from "../engine/scene/contracts";
import {
  AD_PAGE_ID,
  HARVESTED_AD_PAGE,
} from "./__fixtures__/scene-nodes";
import { sceneLayerRows } from "./scene-layers";
import {
  nextSceneSelection,
  sceneAncestorIds,
  sceneExpansion,
  sceneFontOptions,
} from "./scene-session";

/**
 * AD2.7's pure decisions, proven against AD2.2's harvested bytes (the W2.2
 * law). The fixture tree is the one AD2.6's test documents:
 *
 *   frame_ad_root                 (the artboard — routes to the canvas schema)
 *     auto_row_copy               (auto_layout)
 *       text_headline
 *       group_proof               (group)
 *         ellipse_proof_dot
 *         text_proof_stat
 *     rect_accent_bar
 *     line_divider                (§5 unrepresented kind)
 *     image_hero
 */

const ROOT = "frame_ad_root";
const NO_TOGGLES = new Map<string, boolean>();

function derivedScene(nodes: Record<string, Node>): Scene {
  return {
    ...HARVESTED_AD_PAGE,
    nodes: { ...HARVESTED_AD_PAGE.nodes, ...nodes },
  };
}

test("ancestors walk from the node up to the page, nearest first", () => {
  assert.deepEqual(
    sceneAncestorIds(HARVESTED_AD_PAGE, "text_proof_stat"),
    ["group_proof", "auto_row_copy", ROOT],
  );
});

test("a top-level node and an unknown node have no ancestors", () => {
  assert.deepEqual(sceneAncestorIds(HARVESTED_AD_PAGE, ROOT), []);
  assert.deepEqual(sceneAncestorIds(HARVESTED_AD_PAGE, "not_a_node"), []);
  assert.deepEqual(sceneAncestorIds(HARVESTED_AD_PAGE, null), []);
});

test("a cyclic scene terminates instead of hanging the panel", () => {
  // Derived from the harvest with ONE field changed: the artboard adopts its
  // own grandchild's parent, closing a loop the walk must survive.
  const cyclic = derivedScene({
    group_proof: {
      ...HARVESTED_AD_PAGE.nodes.group_proof,
      children: [
        ...HARVESTED_AD_PAGE.nodes.group_proof.children,
        "auto_row_copy",
      ],
    },
  });
  const chain = sceneAncestorIds(cyclic, "ellipse_proof_dot");
  assert.equal(new Set(chain).size, chain.length);
  assert.ok(chain.includes("group_proof"));
});

test("the seeded expansion opens the artboard, so the panel is never one row", () => {
  const expanded = sceneExpansion(
    HARVESTED_AD_PAGE,
    AD_PAGE_ID,
    null,
    NO_TOGGLES,
  );
  assert.deepEqual([...expanded], [ROOT]);
  // The defect this closes: with an EMPTY set the real tree shows one row.
  assert.equal(sceneLayerRows(HARVESTED_AD_PAGE, AD_PAGE_ID, new Set()).length, 1);
  const rows = sceneLayerRows(HARVESTED_AD_PAGE, AD_PAGE_ID, expanded);
  assert.deepEqual(
    rows.map((row) => row.nodeId),
    [ROOT, "auto_row_copy", "rect_accent_bar", "line_divider", "image_hero"],
  );
});

test("selecting a deep node reveals it — every ancestor is seeded open", () => {
  const expanded = sceneExpansion(
    HARVESTED_AD_PAGE,
    AD_PAGE_ID,
    "text_proof_stat",
    NO_TOGGLES,
  );
  const rows = sceneLayerRows(HARVESTED_AD_PAGE, AD_PAGE_ID, expanded);
  assert.ok(rows.some((row) => row.nodeId === "text_proof_stat"));
});

test("a user's own toggle wins over the seed, in both directions", () => {
  const collapsed = sceneExpansion(
    HARVESTED_AD_PAGE,
    AD_PAGE_ID,
    "text_proof_stat",
    new Map([["auto_row_copy", false]]),
  );
  assert.equal(collapsed.has("auto_row_copy"), false);
  assert.equal(collapsed.has(ROOT), true);

  const opened = sceneExpansion(
    HARVESTED_AD_PAGE,
    AD_PAGE_ID,
    null,
    new Map([["group_proof", true]]),
  );
  assert.equal(opened.has("group_proof"), true);
});

test("an unknown page seeds nothing (no other page's nodes leak in)", () => {
  assert.deepEqual(
    [...sceneExpansion(HARVESTED_AD_PAGE, "page_missing", null, NO_TOGGLES)],
    [],
  );
  assert.deepEqual(
    [...sceneExpansion(HARVESTED_AD_PAGE, null, null, NO_TOGGLES)],
    [],
  );
});

test("a plain click replaces the selection; an additive one accumulates", () => {
  assert.deepEqual(nextSceneSelection([], "text_headline", false), [
    "text_headline",
  ]);
  assert.deepEqual(
    nextSceneSelection(["text_headline"], "image_hero", false),
    ["image_hero"],
  );
  assert.deepEqual(
    nextSceneSelection(["text_headline"], "image_hero", true),
    ["text_headline", "image_hero"],
  );
});

test("an additive click on a member removes it; the primary is index 0", () => {
  assert.deepEqual(
    nextSceneSelection(["text_headline", "image_hero"], "image_hero", true),
    ["text_headline"],
  );
  // Dropping the primary promotes the next member rather than clearing.
  assert.deepEqual(
    nextSceneSelection(["text_headline", "image_hero"], "text_headline", true),
    ["image_hero"],
  );
  assert.deepEqual(
    nextSceneSelection(["text_headline"], "text_headline", true),
    [],
  );
});

test("a null press clears, additive or not", () => {
  assert.deepEqual(nextSceneSelection(["text_headline"], null, false), []);
  assert.deepEqual(nextSceneSelection(["text_headline"], null, true), []);
});

test("font options lead with Inter and dedupe keeping library order", () => {
  assert.deepEqual(
    sceneFontOptions(["Satoshi", "Inter", "Playfair"], ["Satoshi", "Cabinet"]),
    ["Inter", "Satoshi", "Playfair", "Cabinet"],
  );
});

test("both fetches empty still yields the one safe option", () => {
  assert.deepEqual(sceneFontOptions([], []), ["Inter"]);
});

/**
 * AD4.E step 2 — the multi-select CLOSURE guard. `nextSceneSelection`'s rule is
 * proven above; what this pins is that the rule is actually reachable, and that
 * amendment 2's deferral held.
 *
 * §1.7: "additive multi-select (shift/⌘-click)" — the modifier the panel saw is
 * what the layers row reports, so the pure rule is never handed a hardcoded
 * `false`. §1.8 (amendment 2): with N selected the inspector shows the
 * FIRST-selected element's schema and the merged panel — common sections with
 * per-field "Mixed" presentation — is deferred to §7, so no mixed-value
 * vocabulary may leak into the ad inspector's props.
 *
 * A `.tsx` cannot be imported under this runner (`tsx --test`, no DOM), so the
 * component is read off disk — `scene-hydrate.test.ts`'s technique.
 */
const AD_LAYERS_SOURCE = readFileSync(
  join(
    dirname(fileURLToPath(import.meta.url)),
    "../../chat-shell/components/ad-dummy-inspectors.tsx",
  ),
  "utf8",
);

test("§1.7: a layers row reports the modifier it saw, and every member stays lit", () => {
  const body = AD_LAYERS_SOURCE.slice(
    AD_LAYERS_SOURCE.indexOf("export function AdSceneLayers"),
    AD_LAYERS_SOURCE.indexOf("function LayersControls"),
  );
  assert.ok(body.length > 0, "AdSceneLayers not found in ad-dummy-inspectors.tsx");

  // All three modifiers, because "shift/⌘-click" on a trackpad Mac is also
  // ctrl-click on the same build shipped to Windows.
  assert.ok(
    body.includes("event.shiftKey || event.metaKey || event.ctrlKey"),
    "the row must pass the real modifier state to onSelectLayer",
  );
  const call = body.indexOf("onSelectLayer?.(");
  assert.ok(call >= 0, "the row must call onSelectLayer");
  assert.ok(
    body
      .slice(call, body.indexOf(")", body.indexOf("ctrlKey", call)))
      .includes("row.nodeId"),
    "onSelectLayer takes the row's node id and that modifier, in that order",
  );

  // The highlight is the WHOLE set, not just the primary — otherwise an
  // additive selection would be invisible and §1.7 unusable.
  assert.ok(
    body.includes("selectedIds.includes(row.nodeId)"),
    "every selected member must render as selected, not only the primary",
  );
});

test("§1.8: the deferred merged panel leaks no mixed-value vocabulary into ad props", () => {
  // Amendment 2 ships the first-selected schema, whole. A `Mixed` sentinel or a
  // `commonSections` prop appearing here would mean the §7 panel had started
  // arriving piecemeal.
  for (const remnant of ["Mixed", "mixedValue", "commonSections", "mergedPanel"]) {
    assert.ok(
      !AD_LAYERS_SOURCE.includes(remnant),
      `the ad inspector props must not carry "${remnant}" — §1.8 defers it to §7`,
    );
  }
});
