// The validator as the harness calls it: the site's files handed over (not read from a
// workspace), missing files named as the spike named them, and the CLI that imports a site's
// agent-written sections from their module paths.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { validateSite } from "../src/validate";
import { garner, site as readSite } from "./fixtures/garner";

const site = readSite("garner-syracuse");
const brand = garner();
const pages = { "/": site.pages["/"], "/analysis": site.pages["/analysis"] };

test("a missing page.json or shell.json says it does not exist yet", () => {
  const result = validateSite({ pages: {}, shell: null }, brand, {});
  assert.equal(result.valid, false);
  assert.deepEqual(
    result.errors.map((e) => e.split(":")[0]),
    ["page.json", "shell.json"],
  );
  assert.ok(result.errors.every((e) => e.includes("does not exist yet; create it with write_file")));
});

test("a file given as its text is parsed; text that is not JSON names the file", () => {
  const asText = { "/": JSON.stringify(pages["/"]), "/analysis": JSON.stringify(pages["/analysis"]) };
  assert.deepEqual(validateSite({ pages: asText, shell: JSON.stringify(site.shell) }, brand, {}), { valid: true, errors: [] });
  const broken = validateSite({ pages: { ...asText, "/analysis": "{ not json" }, shell: site.shell }, brand, {});
  assert.ok(broken.errors.some((e) => e.startsWith("pages/analysis.json: not valid JSON")), broken.errors.join("\n"));
});

test("the CLI validates a site with an agent section imported from its module path", () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const run = (page: unknown) =>
    JSON.parse(
      execFileSync(process.execPath, ["--import", "tsx", "bin/validate-site.ts"], {
        cwd: root,
        input: JSON.stringify({
          files: { pages: { ...pages, "/": page }, shell: site.shell },
          brand,
          agentSectionModules: { QuoteBand: fileURLToPath(new URL("./fixtures/section-example.tsx", import.meta.url)) },
        }),
      }).toString(),
    );
  const withQuote = (surface: string) => {
    const page = structuredClone(pages["/"]);
    page.content.push({ type: "QuoteBand", props: { id: "quote", surface, quote: "Fewer surprises.", attribution: "A buyer" } });
    return page;
  };
  assert.deepEqual(run(withQuote("page")), { valid: true, errors: [] });
  const refused = run(withQuote("green"));
  assert.equal(refused.valid, false);
  assert.ok(refused.errors.some((e: string) => /^page\.content\.\d+\(quote\)\.surface/.test(e)), refused.errors.join("\n"));
});
