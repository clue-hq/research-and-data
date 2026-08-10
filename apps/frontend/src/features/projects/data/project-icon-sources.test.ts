import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";
import { projectIconSources } from "../config/project-icon-sources";

test("every project icon points to a committed Figma SVG export", () => {
  for (const [name, source] of Object.entries(projectIconSources)) {
    assert.match(source, /^\/icons\/projects\/.+\.svg$/, `${name} must use the project icon library`);
    assert.ok(existsSync(resolve(process.cwd(), "public", source.slice(1))), `${name} is missing ${source}`);
  }

  assert.ok(
    !(Object.values(projectIconSources) as string[]).includes("/icons/projects/table.svg"),
  );
});
