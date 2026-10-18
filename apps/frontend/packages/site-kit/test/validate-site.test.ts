// The validator as the harness calls it: the site's files handed over (not read from a
// workspace), missing files named as the spike named them, and the CLI that imports a site's
// agent-written sections from their module paths.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import { validateSite } from "../src/validate";
import { garner, site as readSite } from "./fixtures/garner";
import { schema as quoteSchema } from "./fixtures/section-example";

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

test("the CLI checks an agent section against its stored props JSON Schema, never importing it", () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const run = (page: unknown) =>
    JSON.parse(
      execFileSync(process.execPath, ["--import", "tsx", "bin/validate-site.ts"], {
        cwd: root,
        input: JSON.stringify({
          files: { pages: { ...pages, "/": page }, shell: site.shell },
          brand,
          agentSectionSchemas: { QuoteBand: z.toJSONSchema(quoteSchema) },
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

test("a stored schema that cannot be read is named, not ignored", () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const out = JSON.parse(
    execFileSync(process.execPath, ["--import", "tsx", "bin/validate-site.ts"], {
      cwd: root,
      input: JSON.stringify({ files: { pages, shell: site.shell }, brand, agentSectionSchemas: { Broken: { type: "no-such-type" } } }),
    }).toString(),
  );
  assert.equal(out.valid, false);
  assert.ok(out.errors.some((e: string) => e.startsWith("agent_sections.Broken: its stored props schema could not be read")), out.errors.join("\n"));
});

// Plan 5 (ruling R2, R8): alt texts are plain text of at most 300 characters.
test("alt texts are plain text of at most 300 characters, on our images, the shell's logos and copied images", () => {
  const MESSAGE = "alt text is plain text of at most 300 characters, with no line breaks or control characters";
  const withAlts = (feature: string, header: string, clone: Record<string, string>) => {
    const home = structuredClone(site.pages["/"]);
    const analysis = structuredClone(site.pages["/analysis"]);
    analysis.content[0].props.imageAlt = feature;
    const hero = home.content.find((item: { type: string }) => item.type === "ClonedSection")!;
    hero.props.alts = clone;
    const shell = structuredClone(site.shell);
    shell.header.accountLogoAlt = header;
    shell.header.logoAlt = 'Garner "Health"';
    shell.footer.logoAlt = "Garner";
    return validateSite({ pages: { "/": home, "/analysis": analysis }, shell }, brand, {});
  };
  const ok = 'Dr. "Smith" & <team>';
  assert.deepEqual(withAlts(ok, ok, { "0.1": ok }), { valid: true, errors: [] });
  const bad = withAlts("x".repeat(301), "line\nbreak", { "0.1": "x".repeat(301) });
  assert.equal(bad.valid, false);
  for (const field of ["imageAlt", "accountLogoAlt", "alts.0.1"]) {
    assert.ok(bad.errors.some((error) => error.includes(field) && error.endsWith(MESSAGE)), `${field}: ${bad.errors.join("\n")}`);
  }
  const spanKey = withAlts("", "", { "0.1~2": "x" });
  assert.equal(spanKey.valid, false, spanKey.errors.join("\n"));
});
