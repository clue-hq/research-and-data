// Spike (publishing live sites, phase 1 Task 1): the server's HTML for a real site is taken over in a
// browser (jsdom) by the same React tree with no hydration mismatch.
import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
// The render-only Render, as the live page draws on both sides (it carries none of the editor).
import { Render } from "@puckeditor/core/rsc";
import type { Config, Data } from "@puckeditor/core";
import { fillClone } from "../src/clone";
import { makeConfig } from "../src/config";
import { garner, site as readSite } from "./fixtures/garner";
import { render as quoteRender, schema as quoteSchema } from "./fixtures/section-example";

const brand = garner();
const stored = readSite("garner-syracuse");

test("spike: every Garner route hydrates with zero recoverable errors", async () => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>");
  Object.assign(globalThis, { window: dom.window, document: dom.window.document });
  // Node 21+ ships a getter-only global `navigator`, so it is redefined rather than assigned.
  Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true, writable: true });
  const { hydrateRoot } = await import("react-dom/client");
  const agentSections = { QuoteBand: { schema: quoteSchema, render: quoteRender as never } };
  for (const route of Object.keys(stored.pages)) {
    const data = structuredClone(stored.pages[route]) as Data;
    if (route === "/") data.content.push({ type: "QuoteBand", props: { id: "quote", surface: "brand", quote: "Fewer surprises.", attribution: "A buyer" } } as never);
    const config = makeConfig(brand, { cloneHtml: fillClone, basePath: "/acme", shell: stored.shell, agentSections }) as Config;
    const html = renderToString(createElement(Render as never, { config, data } as never));
    const container = dom.window.document.createElement("div");
    container.innerHTML = html;
    dom.window.document.body.appendChild(container);
    const errors: string[] = [];
    const root = hydrateRoot(container, createElement(Render as never, { config, data } as never), {
      onRecoverableError: (error) => errors.push(String((error as Error)?.message ?? error)),
    });
    await new Promise((resolve) => setTimeout(resolve, 50));
    assert.deepEqual(errors, [], `route ${route} hydrated with mismatches`);
    assert.ok(container.querySelector('[data-agent-section="QuoteBand"]') || route !== "/", "the agent section is there");
    root.unmount();
    container.remove();
  }
});
