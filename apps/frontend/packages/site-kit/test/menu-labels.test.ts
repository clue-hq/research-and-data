// Plan 6 (ruling R8): a menu label typed in place on the canvas is written to the header's props.
import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import { markMenuLabels, writeMenuLabel } from "../src/editor/menu-labels";

test("a page label is written to menuLabels; emptied, the entry goes", () => {
  assert.deepEqual(writeMenuLabel({ id: "header" }, "page:/team", "Who we are"), { id: "header", menuLabels: { team: "Who we are" } });
  assert.deepEqual(writeMenuLabel({ id: "header", menuLabels: { _home: "Home" } }, "page:/", "Start"), { id: "header", menuLabels: { _home: "Start" } });
  assert.deepEqual(writeMenuLabel({ id: "header", menuLabels: { team: "Who" } }, "page:/team", ""), { id: "header" });
});

test("an extra link's label is written to menuExtra; emptied, it keeps the old one", () => {
  const props = { id: "header", menuExtra: [{ label: "Pricing", href: "https://seller.example/pricing" }] };
  assert.deepEqual(writeMenuLabel(props, "extra:0", "Plans"), { id: "header", menuExtra: [{ label: "Plans", href: "https://seller.example/pricing" }] });
  assert.equal(writeMenuLabel(props, "extra:0", ""), null);
  assert.equal(writeMenuLabel(props, "extra:3", "Nope"), null);
});

test("typing a menu label in place writes it once, on leaving", () => {
  const dom = new JSDOM(`<nav id="root"><a href="/team" data-clue-el="menu.team" data-clue-menu-source="page:/team"><span data-clue-menu-label="">Team</span></a></nav>`);
  const root = dom.window.document.getElementById("root") as unknown as HTMLElement;
  const writes: [string, string][] = [];
  const stop = markMenuLabels(root, (source, label) => writes.push([source, label]));
  const label = root.querySelector("[data-clue-menu-label]") as HTMLElement;
  assert.equal(label.getAttribute("contenteditable"), "true");
  label.dispatchEvent(new dom.window.FocusEvent("focus"));
  label.textContent = "  Who we are ";
  label.dispatchEvent(new dom.window.FocusEvent("blur"));
  label.dispatchEvent(new dom.window.FocusEvent("focus"));
  label.dispatchEvent(new dom.window.FocusEvent("blur"));
  assert.deepEqual(writes, [["page:/team", "Who we are"]], "an unchanged label writes nothing");
  stop();
  assert.equal(label.getAttribute("contenteditable"), null);
});
