// The device menu's Tablet and Mobile pin the canvas to 768px and 375px. The web stage stacks its
// canvas in a column, so the canvas's `flex: 1 1 auto` only grows its height there; the site stage
// lays the page panel and the canvas out in a ROW (`.siteStageBody`), where the same flex grew the
// canvas back to the full width and the site never showed its tablet or mobile layout (2026-10-29).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const css = readFileSync(new URL("./chat-shell.module.css", import.meta.url), "utf8");

function declarations(selector: RegExp): string {
  // The rule whose WHOLE selector this is: it follows the previous rule's brace (or a comment).
  const match = css.match(new RegExp(`(?:^|\\}|\\*/)\\s*${selector.source}\\s*\\{([^}]*)\\}`));
  assert.ok(match, `no rule for ${selector.source}`);
  return match[1];
}

test("in the site stage's row, a tablet or mobile canvas keeps its width instead of growing", () => {
  const rule = declarations(/\.siteStageBody > \.webCanvasTablet,\s*\.siteStageBody > \.webCanvasMobile/);
  assert.match(rule, /flex-grow:\s*0;/);
});

test("the device widths themselves stay the engine's canonical viewports", () => {
  assert.match(declarations(/\.webCanvasTablet/), /width:\s*768px;/);
  assert.match(declarations(/\.webCanvasMobile/), /width:\s*375px;/);
});
