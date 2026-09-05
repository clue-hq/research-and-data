import assert from "node:assert/strict";
import test from "node:test";

import type { WebPageSummary } from "../engine/webDocuments";
import { cloneTextEditsFor } from "./clone-text-edits";

const OVERRIDES = {
  ":nth-child(2)": { text: "Second", bold: false, italic: false, underline: false },
  ":nth-child(1)": { text: "First", bold: true, italic: false, underline: false },
};

function page(): WebPageSummary {
  return {
    id: "home",
    name: "Home",
    route: "/",
    root: "root",
    nodes: {
      root: { id: "root", kind: "container", classes: "", children: ["sec_hero", "sec_two"] },
      sec_hero: { id: "sec_hero", kind: "section", classes: "", children: ["frg_hero"] },
      frg_hero: {
        id: "frg_hero",
        kind: "fragment",
        classes: "",
        fragment_id: "frag_a",
        text_overrides: OVERRIDES,
      },
      // A section that is NOT a clone wrapper: two children, neither a fragment.
      sec_two: { id: "sec_two", kind: "section", classes: "", children: ["txt", "img"] },
      txt: { id: "txt", kind: "text", classes: "" },
      img: { id: "img", kind: "image", classes: "" },
    },
  };
}

/** The list belongs to the FRAGMENT node — that is where the engine stores an
 * override. But a marketer clicking a cloned band on the canvas usually selects
 * its wrapper section (the pin is born wrapped), so the wrapper has to find its
 * way to the same list rather than showing nothing. */
test("the fragment itself owns its overrides", () => {
  assert.deepEqual(cloneTextEditsFor(page(), "frg_hero"), {
    nodeId: "frg_hero",
    overrides: [
      { path: ":nth-child(1)", override: OVERRIDES[":nth-child(1)"] },
      { path: ":nth-child(2)", override: OVERRIDES[":nth-child(2)"] },
    ],
  });
});

test("a wrapper section whose only child is a clone points at that clone", () => {
  const result = cloneTextEditsFor(page(), "sec_hero");
  assert.equal(result?.nodeId, "frg_hero");
  assert.deepEqual(
    result?.overrides.map((entry) => entry.path),
    [":nth-child(1)", ":nth-child(2)"],
  );
});

test("anything else owns no list at all", () => {
  assert.equal(cloneTextEditsFor(page(), "sec_two"), null);
  assert.equal(cloneTextEditsFor(page(), "txt"), null);
  assert.equal(cloneTextEditsFor(page(), "root"), null);
  assert.equal(cloneTextEditsFor(page(), "gone"), null);
  assert.equal(cloneTextEditsFor(page(), null), null);
});

/** An un-edited clone is still a clone: the binding exists (the selection rule
 * matched) and the list is simply empty. The section's own render decides not to
 * put an empty list on screen — that is presentation, not selection. */
test("a clone nobody has edited yields an empty list, not null", () => {
  const bare = page();
  delete bare.nodes!.frg_hero.text_overrides;
  assert.deepEqual(cloneTextEditsFor(bare, "frg_hero"), { nodeId: "frg_hero", overrides: [] });
});
