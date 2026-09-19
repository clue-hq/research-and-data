import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";

// sha256 of the dummy's projects-directory.module.css at port-of-spain@9fc902a. Recompute with
// `shasum -a 256 <dummy path>` when the founder re-lifts the screen; never edit the CSS here.
const DUMMY_CSS_SHA256 =
  "8882951e79326cb194534766a4de275536468bd39a954aa31375e8a704b9ad33";

test("the lifted directory CSS is byte-identical to the dummy's", () => {
  const bytes = readFileSync(
    new URL("./projects-directory.module.css", import.meta.url),
  );
  assert.equal(createHash("sha256").update(bytes).digest("hex"), DUMMY_CSS_SHA256);
});

/**
 * The one sanctioned deviation from byte-identity (founder ruling R7,
 * 2026-08-17, recorded at `chat-shell/components/chat-surface.tsx:76`): the
 * (protected) layout's `ProjectApplicationShell` already wraps every
 * `/projects*` route in an `ApplicationShell`, so a screen that embedded its
 * own would mount the navigation rail twice. The dummy has no layout-level
 * shell and therefore carries the wrapper; here it must not.
 */
test("the lifted screen embeds no second ApplicationShell (ruling R7)", () => {
  const source = readFileSync(
    new URL("./projects-screen.tsx", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(source, /ApplicationShell/);
  // The content inside the one shell is still the dummy's, unchanged.
  assert.match(
    source,
    /<main className=\{styles\.screen\} aria-label=\{projectId \? "Project home" : "Projects"\}>/,
  );
  assert.match(source, /<ProjectDirectoryDialog controller=\{controller\} \/>/);
});
