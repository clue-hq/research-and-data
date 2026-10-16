import assert from "node:assert/strict";
import { test } from "node:test";
import { garner } from "../../site-kit/test/fixtures/garner";
import { buildPageConfig, shellFieldDescriptions } from "../src/client/config";
import { describeFields, fieldsForComponent, humanize, puckFieldsFromJsonSchema } from "../src/client/fields";

const brand = garner();
const config = buildPageConfig(brand, null, []);
const byName = <T extends { name: string }>(items: T[]) => Object.fromEntries(items.map((item) => [item.name, item]));

test("labels read like words", () => {
  assert.equal(humanize("buttonHref"), "Button href");
  assert.equal(humanize("cta_label"), "Cta label");
  assert.equal(humanize("AnalysisSteps"), "Analysis steps");
});

test("a built-in section describes its fields with the dock's kinds", () => {
  const fields = byName(fieldsForComponent(config, brand, "FeatureSplit", { id: "what" }));
  assert.equal(fields.heading.kind, "text");
  assert.equal(fields.body.kind, "textarea");
  assert.equal(fields.image.kind, "image");
  assert.equal(fields.buttonHref.kind, "link");
  assert.equal(fields.buttonHref.label, "Button link");
  assert.equal(fields.imageSide.kind, "select");
  assert.equal(fields.surface.kind, "select");
  assert.ok(fields.surface.options?.some((option) => option.label === "Brand" && option.value === "brand"));
});

test("a list field describes its items", () => {
  const fields = byName(fieldsForComponent(config, brand, "StatsBand", { id: "proof" }));
  assert.equal(fields.stats.kind, "list");
  assert.deepEqual(fields.stats.item?.map((item) => [item.name, item.kind]), [
    ["value", "text"],
    ["label", "textarea"],
  ]);
});

test("a cloned section shows its slots by name and kind, never the clone machinery", () => {
  const clone = Object.values(brand.clones)[0];
  const fields = fieldsForComponent(config, brand, "ClonedSection", { fragmentId: clone.id, id: "hero" });
  assert.ok(fields.length > 0);
  assert.ok(fields.every((field) => field.name.startsWith("slots.")));
  const slots = byName(fields);
  assert.deepEqual([slots["slots.headline"].kind, slots["slots.headline"].label], ["textarea", "Headline"]);
  assert.equal(slots["slots.cta_href"].kind, "link");
  assert.equal(slots["slots.visible"].kind, "boolean");
  assert.deepEqual(fieldsForComponent(config, brand, "ClonedSection", { fragmentId: "frag_missing", id: "x" }), []);
});

test("the header and footer describe their own fields", () => {
  const shell = shellFieldDescriptions(brand);
  const header = byName(shell.header);
  assert.equal(header.preparedFor.kind, "text");
  assert.equal(header.accountLogo.kind, "image");
  assert.equal(header.ctaHref.kind, "link");
  assert.deepEqual(header.nav.item?.map((item) => [item.name, item.kind]), [
    ["label", "text"],
    ["href", "link"],
  ]);
  assert.deepEqual(shell.footer.map((field) => [field.name, field.kind]), [
    ["legal", "text"],
    ["privacyHref", "link"],
    ["termsHref", "link"],
  ]);
});

test("an agent section's props schema becomes inline-editable Puck fields and dock fields", () => {
  const puck = puckFieldsFromJsonSchema({
    type: "object",
    properties: {
      id: { type: "string" },
      heading: { type: "string" },
      body: { type: "string" },
      ctaHref: { type: "string" },
      heroImage: { type: "string" },
      tone: { type: "string", enum: ["calm", "bold"] },
      featured: { type: "boolean" },
      count: { type: "integer" },
      steps: { type: "array", items: { type: "object", properties: { title: { type: "string" } } } },
      tags: { type: "array", items: { type: "string" } },
    },
  }) as Record<string, { type: string; contentEditable?: boolean }>;
  assert.equal("id" in puck, false);
  assert.deepEqual([puck.heading.type, puck.heading.contentEditable], ["text", true]);
  assert.deepEqual([puck.body.type, puck.body.contentEditable], ["textarea", true]);
  assert.deepEqual([puck.ctaHref.type, puck.ctaHref.contentEditable], ["text", false]);
  assert.equal(puck.heroImage.type, "custom");
  assert.equal("tags" in puck, false, "an array of plain strings has no dock control yet");
  const described = byName(describeFields(puck as never));
  assert.deepEqual(
    ["heading", "body", "ctaHref", "heroImage", "tone", "featured", "count", "steps"].map((name) => described[name].kind),
    ["text", "textarea", "link", "image", "select", "boolean", "number", "list"],
  );
});

test("the button style and surface choices come from this brand", () => {
  const fields = byName(fieldsForComponent(config, brand, "FeatureSplit", { id: "what" }));
  assert.equal(fields.buttonLook.kind, "select");
  assert.deepEqual(fields.buttonLook.options?.[0], { label: "Standard", value: "" });
  const looks = fields.buttonLook.options!.slice(1);
  assert.ok(looks.length > 0, "Garner's kit records button styles");
  // The marketer sees words ("Outline", "Text only", "Filled 2"), never a variant or token name.
  assert.ok(looks.every((option) => option.label.length > 0 && !option.label.includes(".")), JSON.stringify(looks));
  const surfaces = fields.surface.options!.map((option) => option.value);
  assert.deepEqual(surfaces.slice(0, 6), ["page", "card", "muted", "brandSubtle", "brand", "inverse"]);
  assert.ok(surfaces.length > 6 && surfaces.includes("canvas"), "the brand's own surfaces follow the six");
});
