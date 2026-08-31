import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { it } from "node:test";
import { fileURLToPath } from "node:url";
import { commitInspectorNumber } from "./use-inspector-controller";

/**
 * Ruling A7, applied to the gradient editor (AD4.0 step 2): a numeric field
 * commits on blur/Enter, never per keystroke. Step 1 of this same task settled
 * it for the Custom W/H boxes after the browser showed typing "108" persisting
 * three document versions; review found the angle and stop-position inputs
 * still writing per keystroke — clearing the angle box and typing "137" made
 * FOUR versions and four undo steps, the first a spurious `angle: 0`.
 *
 * The decision is pure and tested directly. The WIRING is pinned by reading
 * `inspector-primitives.tsx` off disk, because a `.tsx` cannot be imported
 * under this runner (it pulls a CSS module) — the same technique
 * `scene-hydrate.test.ts` uses to pin the ad inspector's preset vocabulary.
 */

const PRIMITIVES_SOURCE = readFileSync(
  join(
    dirname(fileURLToPath(import.meta.url)),
    "../components/inspector-primitives.tsx",
  ),
  "utf8",
);

it("A7: mid-edit text commits NOTHING — it is not a request to write 0", () => {
  // The retired inline expression was `clamp(Number(value) || 0, 0, max)`,
  // which turned every one of these into a real, persisted 0.
  for (const raw of ["", "   ", "-", "1e", "abc", "#fff"]) {
    assert.equal(commitInspectorNumber(raw, 360), null, JSON.stringify(raw));
  }
});

it("A7: a typed number commits itself, clamped to the field's own range", () => {
  assert.equal(commitInspectorNumber("137", 360), 137);
  assert.equal(commitInspectorNumber(" 45 ", 360), 45);
  // Fractional positions are typable (the input is free text, not stepped).
  assert.equal(commitInspectorNumber("33.5", 100), 33.5);
  // The clamp is the dummy's own, unchanged by this ruling.
  assert.equal(commitInspectorNumber("400", 360), 360);
  assert.equal(commitInspectorNumber("400", 100), 100);
  assert.equal(commitInspectorNumber("-5", 360), 0);
});

it("A7: the gradient angle and every stop position are wired to COMMIT, not to keystrokes", () => {
  // Typing N characters produces zero writes: `onChange` only drafts. The one
  // commit is `onCommit` (blur/Enter), which `InspectorInput` already ships.
  assert.match(
    PRIMITIVES_SOURCE,
    /ariaLabel="Gradient angle"\s*\n\s*onChange=\{\(value\) => setDraft\(\{ field: "angle", value \}\)\}\s*\n\s*onCommit=/,
  );
  assert.match(
    PRIMITIVES_SOURCE,
    /ariaLabel=\{`Gradient stop \$\{index \+ 1\} position`\}[\s\S]{0,200}?onChange=\{\(value\) => setDraft\([\s\S]{0,120}?onCommit=/,
  );
  // And the per-keystroke writes they replaced are gone, both of them.
  assert.doesNotMatch(PRIMITIVES_SOURCE, /angle: clamp\(Number\(value\)/);
  assert.doesNotMatch(PRIMITIVES_SOURCE, /position: clamp\(Number\(value\)/);
});

it("A16 follow-up: the colour picker cannot render NaN for a value it cannot place", () => {
  // `hexToHsv` parsed any string as hex, so a token `$name` (which A16 put on
  // swatches users open often) or the `none` sentinel produced {NaN,NaN,NaN}
  // and the plane rendered `NaN%`. It is picker-internal and unimportable
  // here, so the guard is pinned at the source: a non-hex returns a defined
  // HSV before any parsing happens.
  assert.match(
    PRIMITIVES_SOURCE,
    /function hexToHsv[\s\S]{0,600}?if \(!\/\^\[0-9a-fA-F\]\{6\}\$\/\.test\(normalized\)\) \{\s*\n\s*return \{ h: 0, s: 0, v: 0 \};/,
  );
});
