// S2a-2 §2.5: an agent section that passes the write-time checks but still throws while the editor's
// in-place widgets are in its props falls back, in Edit mode only, to drawing with its raw props (the
// strings Puck stores). It is then edited in the side panel, never shown as an empty failed box. A
// section that also fails with plain text keeps the failed marker; the published page never takes
// this path (EditorParts is injected only by the editor).
import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { makeConfig, type EditorParts } from "../src/config";
import { fillClone } from "../src/clone";
import { garner } from "./fixtures/garner";

const brand = garner();

function jsdom() {
  const dom = new JSDOM("<!doctype html><html><body></body></html>");
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, IS_REACT_ACT_ENVIRONMENT: true });
  Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true, writable: true });
  return dom;
}

type Props = Record<string, unknown>;
/** Throws on anything but text, as a section that string-processes its prose does. */
const Shouting = { schema: { safeParse: () => ({ success: true }) }, render: ((props: { headline: string }) => <h2>{props.headline.toUpperCase()}</h2>) as never };
/** Throws on anything but text, and when it is handed the page's styling of it as a prop. */
const Picky = {
  schema: { safeParse: () => ({ success: true }) },
  render: ((props: Props) => {
    if ("_edits" in props) throw new Error("given _edits");
    if (typeof props.headline !== "string") throw new Error("not text");
    return <h2>{props.headline}</h2>;
  }) as never,
};
const Broken = { schema: { safeParse: () => ({ success: true }) }, render: (() => { throw new Error("always broken"); }) as never };

function editorParts(raw: Record<string, Props>, calls: string[]): EditorParts {
  return {
    AssetPicker: () => null,
    CloneEditor: () => null,
    useRawProps: () => (id) => {
      calls.push(id);
      return raw[id];
    },
  };
}

async function draw(editor: EditorParts | undefined, type: string, props: Props) {
  const dom = jsdom();
  const config = makeConfig(brand, { agentSections: { Shouting, Broken, Picky }, editor, cloneHtml: fillClone, mode: "page" });
  const render = (config.components as Record<string, { render: (props: Props) => ReactNode }>)[type].render;
  const container = dom.window.document.createElement("div");
  dom.window.document.body.appendChild(container);
  const warnings: string[] = [];
  const warn = console.warn;
  console.warn = (...args: unknown[]) => warnings.push(args.map(String).join(" "));
  const root = createRoot(container, { onCaughtError: () => undefined });
  try {
    await act(async () => root.render(<>{render(props)}</>));
    return { html: container.innerHTML, warnings };
  } finally {
    console.warn = warn;
    await act(async () => root.unmount());
  }
}

const inlineWidget = <span data-inline-text="">Fewer surprises</span>;
/** Every section draws inside the box that scopes its manual styling (config.tsx). */
const scoped = (id: string, html: string) => `<div data-clue-section="${id}" class="clue-section">${html}</div>`;

test("S2a-2: a section that throws only on an in-place widget draws with its raw props in Edit mode", async () => {
  const calls: string[] = [];
  const editor = editorParts({ quote: { id: "quote", surface: "brand", headline: "Fewer surprises" } }, calls);
  const { html, warnings } = await draw(editor, "Shouting", { id: "quote", surface: "brand", headline: inlineWidget, puck: { isEditing: true } });
  assert.equal(html, scoped("quote", '<div data-agent-section="Shouting"><h2>FEWER SURPRISES</h2></div>'));
  assert.deepEqual([...new Set(calls)], ["quote"], "read by the section's id");
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /Shouting/);
});

test("S2a-2: a section that also fails with plain text keeps the failed marker", async () => {
  const calls: string[] = [];
  const editor = editorParts({ broken: { id: "broken", surface: "page" } }, calls);
  const { html } = await draw(editor, "Broken", { id: "broken", surface: "page", puck: { isEditing: true } });
  assert.equal(html, scoped("broken", '<div data-agent-section="Broken"><div data-agent-section-failed="Broken"></div></div>'));
  assert.deepEqual([...new Set(calls)], ["broken"]);
});

test("plan 2: outside Edit mode the editor draws from the raw props (Puck puts its read-only rich text widget in preview); the published page never reads them", async () => {
  const calls: string[] = [];
  const editor = editorParts({ quote: { id: "quote", surface: "brand", headline: "Fewer surprises" } }, calls);
  const preview = await draw(editor, "Shouting", { id: "quote", surface: "brand", headline: inlineWidget, puck: { isEditing: false } });
  assert.equal(preview.html, scoped("quote", '<div data-agent-section="Shouting"><h2>FEWER SURPRISES</h2></div>'));
  assert.ok(calls.includes("quote"));
  const published = await draw(undefined, "Shouting", { id: "quote", surface: "brand", headline: inlineWidget });
  assert.equal(published.html, scoped("quote", '<div data-agent-section="Shouting"><div data-agent-section-failed="Shouting"></div></div>'));
  assert.deepEqual([...preview.warnings, ...published.warnings], []);
});

test("the editor's second try draws from the stored props without their _edits", async () => {
  const calls: string[] = [];
  const edits = { headline: { italic: true } };
  const editor = editorParts({ quote: { id: "quote", surface: "brand", headline: "Fewer surprises", _edits: edits } }, calls);
  // The first draw fails on the in-place widget, so the raw props are read.
  const { html } = await draw(editor, "Picky", { id: "quote", surface: "brand", headline: inlineWidget, _edits: edits, puck: { isEditing: true } });
  assert.equal(html, scoped("quote", '<style data-clue-edits="">[data-clue-section="quote"] [data-clue-el="headline"]{font-style:italic !important}</style><div data-agent-section="Picky"><h2>Fewer surprises</h2></div>'));
  assert.deepEqual([...new Set(calls)], ["quote"]);
});
