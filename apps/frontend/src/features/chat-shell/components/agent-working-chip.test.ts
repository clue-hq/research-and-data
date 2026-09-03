import assert from "node:assert/strict";
import Module from "node:module";
import { it } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AGENT_WORKING_CHIP_LABEL, shouldShowAgentWorkingChip } from "./agent-working-chip.logic";

/*
 * The component imports its CSS module, which node cannot parse as JavaScript
 * (bundler-only syntax). node:test has no CSS-module loader, so the require
 * extension is stubbed to an empty class map — class names are the bundler's
 * business, and nothing here asserts on them. The stub must be installed before
 * the component is loaded, hence the dynamic import inside the test.
 */
(Module as unknown as { _extensions: Record<string, unknown> })._extensions[".css"] = (mod: {
  exports: unknown;
}) => {
  mod.exports = {};
};

it("shows only while the lock is engaged over a real scene", () => {
  assert.equal(shouldShowAgentWorkingChip({ editDisabled: true, hasScene: true }), true);
  assert.equal(shouldShowAgentWorkingChip({ editDisabled: false, hasScene: true }), false);
  assert.equal(shouldShowAgentWorkingChip({ editDisabled: undefined, hasScene: true }), false);
  assert.equal(shouldShowAgentWorkingChip({ editDisabled: true, hasScene: false }), false);
});

it("carries the founder's words, verbatim", () => {
  assert.equal(AGENT_WORKING_CHIP_LABEL, "Designing. Please wait to edit.");
});

it("renders a polite status with a nine-dot grid and the label", async () => {
  const { AgentWorkingChip } = await import("./agent-working-chip");
  const html = renderToStaticMarkup(
    createElement(AgentWorkingChip, { label: AGENT_WORKING_CHIP_LABEL }),
  );
  assert.match(html, /role="status"/);
  assert.match(html, /aria-live="polite"/);
  assert.equal((html.match(/data-dot=""/g) ?? []).length, 9);
  assert.match(html, /Designing\. Please wait to edit\./);
  // The grid is decorative; the label is the accessible name.
  assert.match(html, /aria-hidden="true"/);
});
