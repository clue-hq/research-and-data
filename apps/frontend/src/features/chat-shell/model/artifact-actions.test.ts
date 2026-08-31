import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { ARTIFACT_ACTIONS } from "./artifact-actions";

test("artifact actions preserve the reviewed menu contract", () => {
  assert.deepEqual(ARTIFACT_ACTIONS, [
    "rename",
    "duplicate",
    "undo",
    "redo",
    "versions",
    "archive",
    "delete",
  ]);
});

/**
 * AD4.E (contract §1.12 / §3): the Versions flyout is PRESENT-AND-INERT in v1
 * — "inert until the fast-follow binds real history". Two guards hold that
 * shape from both sides, so deleting the flyout AND binding it both fail
 * loudly rather than passing silently.
 *
 * "Inert" is read precisely, per the controller's R2 ruling: the rows keep the
 * lifted dummy's local radio behaviour (presentation truth — the dummy shows a
 * checked "Current version" and moves the check on click), and what is inert is
 * the DOCUMENT. Nothing in the app listens to the selection, so choosing V2
 * changes no document, no session and no server state.
 *
 * A `.tsx` cannot be imported under this runner (`tsx --test`, no DOM), so the
 * component half is read off disk — the technique `scene-hydrate.test.ts` and
 * `inspector-commit-model.test.ts` already use.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const VERSION_SELECT_EVENT = "clue:artifact-version-select";
const MENU_SOURCE = readFileSync(
  join(HERE, "../components/artifact-action-menu.tsx"),
  "utf8",
);

/** The flyout's four rows, as the dummy renders them (§3). */
const VERSION_ROW_LABELS = [
  "Current version",
  "Version 3",
  "Version 2",
  "Version 1",
];

function sliceBetween(source: string, start: string, end: string): string {
  const from = source.indexOf(start);
  assert.ok(from >= 0, `"${start}" not found in artifact-action-menu.tsx`);
  const to = source.indexOf(end, from);
  assert.ok(to > from, `"${end}" not found after "${start}"`);
  return source.slice(from, to);
}

// ── Guard (a): the DOCUMENT-inert half — nothing listens ────────────────────

test("§3: the version-select event has no listener anywhere in the app", () => {
  // The plan's "no event listener attached", read precisely. Walked the way
  // `no-env-reads-scene.test.ts` walks its slice. Test files are skipped
  // because this one necessarily names the event to assert about it.
  const root = join(HERE, "../../..");
  const mentions: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(path);
        continue;
      }
      if (!/\.tsx?$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) {
        continue;
      }
      if (readFileSync(path, "utf8").includes(VERSION_SELECT_EVENT)) {
        mentions.push(entry.name);
      }
    }
  };
  walk(root);

  // Exactly one site may know the event exists: the dispatcher. Binding real
  // history (the §3/§7 fast-follow) adds a listener here and must rewrite this
  // guard deliberately, never slip past it.
  assert.deepEqual(mentions, ["use-artifact-action-menu-controller.ts"]);
});

// ── Guard (b): the PRESENT half — the rows are still there, and still inert ──

test("§1.12: the four version rows still render", () => {
  const options = sliceBetween(MENU_SOURCE, "const versionOptions = [", "];");
  for (const label of VERSION_ROW_LABELS) {
    assert.ok(
      options.includes(`"${label}"`),
      `the Versions flyout must still offer "${label}"`,
    );
  }
});

test("§3: a version row's only click behaviour is the unlistened select", () => {
  const rows = sliceBetween(MENU_SOURCE, "{versionOptions.map(", "</div>");
  assert.ok(
    rows.includes("onClick={() => onSelectVersion(version.id)}"),
    "the version row must call onSelectVersion and nothing else",
  );
  // No SECOND handler smuggled onto the row — an `onPointerDown` that loaded a
  // revision would be exactly the fast-follow this guard is holding back.
  assert.deepEqual(
    [...new Set(rows.match(/on[A-Z][A-Za-z]*=/g) ?? [])],
    ["onClick="],
  );
  // And the menu wires nothing imperatively either.
  assert.ok(
    !MENU_SOURCE.includes("addEventListener"),
    "the action menu must attach no listeners of its own",
  );
});
