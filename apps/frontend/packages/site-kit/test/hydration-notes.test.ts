// The render page's hydration notes (publishing live sites, final review F3): production React
// minifies its hydration errors, so a note that carries one of those codes reads as a plain sentence
// the agent can act on; every other note, and every prefix naming where it happened, stays as is.
import assert from "node:assert/strict";
import { test } from "node:test";
import { hydrationNote } from "../src/hydration-notes";

const minified = (code: number) =>
  `Minified React error #${code}; visit https://react.dev/errors/${code}?args[]=x for the full message or use the non-minified dev environment for full errors and additional helpful warnings.`;

test("a minified hydration error becomes a plain sentence that keeps its code", () => {
  for (const code of [418, 419, 420, 421, 422, 423, 425]) {
    assert.equal(hydrationNote(`mismatch: ${minified(code)}`), `mismatch: the server and the browser drew this page differently (React #${code})`);
  }
});

test("the prefix naming the section or the page is kept", () => {
  assert.equal(
    hydrationNote(`section failed: Fragile: ${minified(418)}`),
    "section failed: Fragile: the server and the browser drew this page differently (React #418)",
  );
  assert.equal(hydrationNote(`page failed: ${minified(425)}`), "page failed: the server and the browser drew this page differently (React #425)");
});

test("every other note stays exactly as written", () => {
  for (const note of [
    "section failed: Fragile: boom",
    `section failed: Fragile: ${minified(424)}`,
    `mismatch: ${minified(4180)}`,
    `page failed: ${minified(31)}`,
    "mismatch: Hydration failed because the server rendered text didn't match the client.",
  ]) {
    assert.equal(hydrationNote(note), note);
  }
});
