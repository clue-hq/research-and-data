import assert from "node:assert/strict";
import test from "node:test";
import type { WebNode } from "../engine/webDocuments";
import { displayNameForNode, innerElementLabel } from "./node-names";

const nodes: Record<string, WebNode> = {
  sec_a: { id: "sec_a", kind: "section", classes: "", children: ["frg_a"] },
  frg_a: { id: "frg_a", kind: "fragment", classes: "", fragment_id: "frag_" + "ab".repeat(8) },
  sec_b: { id: "sec_b", kind: "section", classes: "", children: ["txt", "btn"] },
  txt: { id: "txt", kind: "text", classes: "", content: "<p>Card infrastructure <em>economics</em>, built for Ramp.</p>" },
  btn: { id: "btn", kind: "button", classes: "", label: "Talk to our team" },
  img: { id: "img", kind: "image", classes: "", asset_id: "asset_x", alt: "Visa card" },
  img2: { id: "img2", kind: "image", classes: "", asset_id: "asset_y", alt: "" },
  box: { id: "box", kind: "container", classes: "" },
  named: { id: "named", kind: "text", classes: "", name: "Eyebrow", content: "Issuing" },
};
const meta = { ["frag_" + "ab".repeat(8)]: { label: "Stripe homepage hero", section_role: "hero" } };

test("a node's own name wins over everything", () => {
  assert.equal(displayNameForNode(nodes.named, nodes, meta), "Eyebrow");
});

test("text is named by its plain words, capped at 40 chars", () => {
  assert.equal(displayNameForNode(nodes.txt, nodes), "Card infrastructure economics, built for");
});

test("buttons by label, images by alt or 'Image', containers by kind", () => {
  assert.equal(displayNameForNode(nodes.btn, nodes), "Talk to our team");
  assert.equal(displayNameForNode(nodes.img, nodes), "Visa card");
  assert.equal(displayNameForNode(nodes.img2, nodes), "Image");
  assert.equal(displayNameForNode(nodes.box, nodes), "Container");
});

test("a fragment is named from the registry meta, and its wrapper section inherits it", () => {
  assert.equal(displayNameForNode(nodes.frg_a, nodes, meta), "Hero — Stripe homepage hero");
  assert.equal(displayNameForNode(nodes.sec_a, nodes, meta), "Hero — Stripe homepage hero");
  // Without meta the clone is still human, never an id.
  assert.equal(displayNameForNode(nodes.frg_a, nodes), "Cloned section");
  assert.equal(displayNameForNode(nodes.sec_b, nodes), "Section");
});

test("inner elements read as tag plus slot when there is one", () => {
  assert.equal(innerElementLabel("h2", "headline"), "h2 · headline");
  assert.equal(innerElementLabel("svg", null), "svg");
  assert.equal(innerElementLabel("P", undefined), "p");
});
