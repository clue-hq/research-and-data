// Tailwind must scan the agent's sections on every compile, not only on an incremental rebuild:
// a class that only an agent-written section uses still gets its CSS.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import postcss from "postcss";
import tailwind from "@tailwindcss/postcss";

test("a fresh compile of globals.css includes classes used only in agent sections", async () => {
  const spike = path.join(__dirname, "..");
  const dir = path.join(spike, "puck", "agent-sections", "tailwind-scan-test");
  fs.mkdirSync(dir, { recursive: true });
  // Assembled here so the class appears in no source file Tailwind could find it in.
  const value = ["37", "25"].join(".");
  fs.writeFileSync(path.join(dir, "Probe.tsx"), `export const probe = <div className="h-[${value}rem]" />;\n`);
  try {
    const from = path.join(spike, "app", "globals.css");
    const out = await postcss([tailwind()]).process(fs.readFileSync(from, "utf8"), { from });
    assert.ok(out.css.includes(`${value}rem`), "the class from the agent section is missing from the CSS");
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
