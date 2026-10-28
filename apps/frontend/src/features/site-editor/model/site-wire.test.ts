// Site loading (2026-10-29): the design API sends each distinct CSS block of the brand's sections
// once (`css_rules`), every section naming its blocks by index with its own scoping class stood in
// by a marker. The reader puts each section's CSS back exactly; an old-shape answer reads as it is.
import assert from "node:assert/strict";
import { test } from "node:test";
import { CLONE_CLASS_MARK, SiteBrandWireSchema } from "./site-wire";

const brand = (clones: Record<string, unknown>) => ({ slug: "s", kit: {}, fonts: [], assets: {}, clones });
const clone = (id: string, extra: Record<string, unknown>) => ({
  id, label: id, html: "<p></p>", slots: {}, wrapper_class: `lumen-frag-${id}`, ...extra,
});

test("each section's CSS is rebuilt from the shared blocks under its own class", () => {
  const wire = {
    schema_version: 2,
    css_rules: [`.${CLONE_CLASS_MARK} .hero { padding: 64px }`, "\n@media (x) { .a { b: c } }", `.${CLONE_CLASS_MARK} p { color: red }`],
    brand: brand({ a: clone("a", { css_rules: [0, 1] }), b: clone("b", { css_rules: [0, 1, 2] }) }),
  };
  const parsed = SiteBrandWireSchema.parse(wire);
  assert.equal(parsed.clones.a.css, ".lumen-frag-a .hero { padding: 64px }\n@media (x) { .a { b: c } }");
  assert.equal(
    parsed.clones.b.css,
    ".lumen-frag-b .hero { padding: 64px }\n@media (x) { .a { b: c } }.lumen-frag-b p { color: red }",
  );
  assert.equal("css_rules" in parsed.clones.a, false, "the frame is handed the plain shape");
});

test("a section sent with its css as it is, and an answer with no shared blocks, read unchanged", () => {
  const kept = SiteBrandWireSchema.parse({ schema_version: 2, css_rules: [], brand: brand({ a: clone("a", { css: ".x{}" }) }) });
  assert.equal(kept.clones.a.css, ".x{}");
  const old = SiteBrandWireSchema.parse({ schema_version: 1, brand: brand({ a: clone("a", { css: ".y{}" }) }) });
  assert.equal(old.clones.a.css, ".y{}");
});

test("a block index the answer does not hold is refused, not drawn as missing CSS", () => {
  assert.throws(() =>
    SiteBrandWireSchema.parse({ schema_version: 2, css_rules: ["a"], brand: brand({ a: clone("a", { css_rules: [0, 3] }) }) }),
  );
});
