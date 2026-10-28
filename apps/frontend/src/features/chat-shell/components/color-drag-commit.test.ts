import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { it } from "node:test";
import { fileURLToPath } from "node:url";
import { colorToCommitOnRelease } from "./color-drag-commit";

/**
 * The Custom tab's colour square and hue slider save ONCE, when the gesture ends.
 *
 * Found in production 2026-10-28: every pointer move over the square (and every step
 * of the hue slider) was a full document save. One six-second drag wrote about 45
 * versions; on Pallet's LinkedIn ad the square saved about once a second for 15
 * minutes, and the text-colour edits made meanwhile were refused as version conflicts
 * and put back. While the pointer moves, only the picker's own swatch follows it.
 *
 * The decision is pure and tested directly. The WIRING is pinned by reading
 * `inspector-primitives.tsx` off disk, because a `.tsx` cannot be imported under this
 * runner (it pulls a CSS module) — the technique `inspector-commit-model.test.ts` uses.
 */

const PRIMITIVES_SOURCE = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "inspector-primitives.tsx"),
  "utf8",
);

/** The JSX attribute value of `handler` on the element labelled `label`. */
function handlerOn(label: string, handler: string): string {
  const start = PRIMITIVES_SOURCE.indexOf(`aria-label="${label}"`);
  assert.notEqual(start, -1, `no element labelled ${label}`);
  const tagStart = PRIMITIVES_SOURCE.lastIndexOf("<", start);
  // The opening tag ends at the first `>` outside any `{...}` (an arrow's `=>` sits
  // inside its handler's braces).
  let braces = 0;
  let tagEnd = tagStart;
  for (; tagEnd < PRIMITIVES_SOURCE.length; tagEnd += 1) {
    const char = PRIMITIVES_SOURCE[tagEnd];
    if (char === "{") braces += 1;
    if (char === "}") braces -= 1;
    if (char === ">" && braces === 0) break;
  }
  const tag = PRIMITIVES_SOURCE.slice(tagStart, tagEnd);
  const at = tag.indexOf(`${handler}={`);
  if (at === -1) return "";
  let depth = 0;
  for (let index = at + handler.length + 1; index < tag.length; index += 1) {
    if (tag[index] === "{") depth += 1;
    if (tag[index] === "}") depth -= 1;
    if (depth === 0) return tag.slice(at, index + 1);
  }
  return tag.slice(at);
}

it("a gesture that ended on a new colour saves that colour once", () => {
  assert.equal(colorToCommitOnRelease("#29251E", "#C69F5A"), "#C69F5A");
});

it("a gesture that never moved, or came back to the saved colour, saves nothing", () => {
  assert.equal(colorToCommitOnRelease("#29251E", null), null);
  assert.equal(colorToCommitOnRelease("#29251E", "#29251E"), null);
  assert.equal(colorToCommitOnRelease("#29251e", "#29251E"), null);
});

/** The body of `const name = (...) => { ... };` in the primitives source. */
function functionBody(name: string): string {
  const start = PRIMITIVES_SOURCE.indexOf(`const ${name} = `);
  assert.notEqual(start, -1, `no ${name}`);
  const open = PRIMITIVES_SOURCE.indexOf("{", PRIMITIVES_SOURCE.indexOf("=>", start));
  let depth = 0;
  for (let index = open; index < PRIMITIVES_SOURCE.length; index += 1) {
    if (PRIMITIVES_SOURCE[index] === "{") depth += 1;
    if (PRIMITIVES_SOURCE[index] === "}") depth -= 1;
    if (depth === 0) return PRIMITIVES_SOURCE.slice(open, index + 1);
  }
  return PRIMITIVES_SOURCE.slice(open);
}

it("moving over the square only previews; it never saves", () => {
  const move = handlerOn("Color saturation and brightness", "onPointerMove");
  assert.notEqual(move, "", "the square still follows the pointer");
  assert.doesNotMatch(move, /commitCustomColor|onColorChange|commitColor/);
  // The handler reads the pointer through this helper, so it must not save either.
  assert.doesNotMatch(
    functionBody("updateSaturationAndValue"),
    /commitCustomColor|onColorChange|commitColor/,
  );
});

it("the square saves when the pointer is released or its capture is lost", () => {
  assert.match(handlerOn("Color saturation and brightness", "onPointerUp"), /finishCustomColor/);
  assert.match(
    handlerOn("Color saturation and brightness", "onLostPointerCapture"),
    /finishCustomColor/,
  );
  assert.doesNotMatch(
    handlerOn("Color saturation and brightness", "onPointerDown"),
    /commitCustomColor|onColorChange|commitColor/,
  );
});

it("a drag shows on the canvas as it moves, through the preview channel", () => {
  // The canvas follows the pointer (founder 2026-10-29); the preview channel is the
  // engine-only half of a write, so it never reaches the save queue.
  assert.match(functionBody("previewCustomColor"), /onColorPreview\?\.\(/);
  assert.doesNotMatch(functionBody("previewCustomColor"), /onColorChange|commitColor/);
});

it("release compares against the colour the gesture STARTED from, not the previewed one", () => {
  // Under live preview the `color` prop is already the previewed colour by the time
  // the pointer is released, so comparing against it would save nothing.
  const finish = functionBody("finishCustomColor");
  assert.match(finish, /gestureStartColorRef/);
  assert.match(functionBody("previewCustomColor"), /gestureStartColorRef/);
});

const CONTROLLER_SOURCE = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../hooks/use-inspector-controller.ts"),
  "utf8",
);
const SCENE_WRITES_SOURCE = readFileSync(
  join(
    dirname(fileURLToPath(import.meta.url)),
    "../../design-editor/hooks/use-scene-inspector-writes.ts",
  ),
  "utf8",
);

it("the controller offers a preview that sends its own event, never the write event", () => {
  const start = CONTROLLER_SOURCE.indexOf("const previewValue = useCallback(");
  assert.notEqual(start, -1, "no previewValue");
  const body = CONTROLLER_SOURCE.slice(start, CONTROLLER_SOURCE.indexOf("\n  );\n", start));
  assert.match(body, /"clue:inspector-property-preview"/);
  assert.doesNotMatch(body, /"clue:inspector-property-change"/);
  assert.match(CONTROLLER_SOURCE, /\n\s+previewValue,\n/, "previewValue is returned");
});

it("the ad lane applies a preview to the canvas engine only, never to the save queue", () => {
  const start = SCENE_WRITES_SOURCE.indexOf("const onPreview = ");
  assert.notEqual(start, -1, "no preview listener");
  const end = SCENE_WRITES_SOURCE.indexOf('"clue:inspector-property-preview", onPreview', start);
  assert.notEqual(end, -1, "the preview listener is registered");
  const body = SCENE_WRITES_SOURCE.slice(start, end);
  assert.match(body, /\.applyOperations\(/);
  assert.doesNotMatch(body, /applyOpsRef|persistAppliedOps|enqueue/);
});

it("every ad colour row hands its preview to the picker", () => {
  for (const file of ["image-inspector.tsx", "ad-dummy-inspectors.tsx"]) {
    const source = readFileSync(join(dirname(fileURLToPath(import.meta.url)), file), "utf8");
    const pickers = source.match(/<ColorControl [^\n]*/g) ?? [];
    assert.ok(pickers.length > 0, file);
    for (const picker of pickers) assert.match(picker, /onColorPreview=\{/, `${file}: ${picker}`);
  }
});

it("sliding the hue only previews; it saves when the slide ends", () => {
  assert.doesNotMatch(
    handlerOn("Color hue", "onChange"),
    /commitCustomColor|onColorChange|commitColor/,
  );
  for (const end of ["onPointerUp", "onKeyUp", "onBlur"]) {
    assert.match(handlerOn("Color hue", end), /finishCustomColor/, end);
  }
});
