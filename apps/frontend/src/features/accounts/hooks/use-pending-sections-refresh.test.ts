import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { anySectionPending } from "./use-pending-sections-refresh";

test("a page is pending when any section is", () => {
  assert.equal(anySectionPending([]), false);
  assert.equal(anySectionPending([{ pending: false }, {}]), false);
  assert.equal(anySectionPending([{ pending: false }, { pending: true }]), true);
});

test("the hook refreshes the server page on an interval only while pending", () => {
  const source = readFileSync(new URL("./use-pending-sections-refresh.ts", import.meta.url), "utf8");
  assert.match(source, /"use client"/);
  assert.match(source, /useRouter\(\)/);
  assert.match(source, /if \(!pending\) return;/);
  assert.match(source, /window\.setInterval\(\(\) => router\.refresh\(\), pollMs\)/);
  assert.match(source, /window\.clearInterval\(interval\)/);
  assert.match(source, /pollMs = 5000/);
});
