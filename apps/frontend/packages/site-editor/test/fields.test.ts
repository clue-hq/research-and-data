import assert from "node:assert/strict";
import { test } from "node:test";
import { buttonLookOptions, cardLooks, surfaceChoices } from "@clue/site-kit";
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
    ["newTab", "boolean"],
  ]);
  assert.deepEqual(shell.footer.map((field) => [field.name, field.kind]), [
    ["legal", "text"],
    ["privacyHref", "link"],
    ["privacyNewTab", "boolean"],
    ["termsHref", "link"],
    ["termsNewTab", "boolean"],
  ]);
});

test("an agent section's props schema becomes Puck fields and dock fields; only marked prose edits in place", () => {
  const puck = puckFieldsFromJsonSchema(
    {
      type: "object",
      properties: {
        id: { type: "string" },
        heading: { type: "string", edit: "inline" },
        body: { type: "string", edit: "inline" },
        caption: { type: "string" },
        ctaHref: { type: "string" },
        heroImage: { type: "string" },
        tone: { type: "string", enum: ["calm", "bold"] },
        featured: { type: "boolean" },
        count: { type: "integer" },
        steps: { type: "array", items: { type: "object", properties: { title: { type: "string", edit: "inline" }, note: { type: "string" } } } },
        tags: { type: "array", items: { type: "string" } },
      },
    },
    brand,
  ) as Record<string, { type: string; contentEditable?: boolean; arrayFields?: Record<string, { type: string; contentEditable?: boolean }> }>;
  assert.equal("id" in puck, false);
  assert.deepEqual([puck.heading.type, puck.heading.contentEditable], ["text", true]);
  assert.deepEqual([puck.body.type, puck.body.contentEditable], ["textarea", true]);
  assert.deepEqual([puck.caption.type, Boolean(puck.caption.contentEditable)], ["text", false], "unmarked text is edited in the side panel");
  assert.deepEqual([puck.ctaHref.type, Boolean(puck.ctaHref.contentEditable)], ["text", false]);
  assert.equal(puck.heroImage.type, "custom");
  assert.deepEqual([puck.steps.arrayFields?.title.type, puck.steps.arrayFields?.title.contentEditable], ["text", true], "marked text inside a list edits in place");
  assert.equal(Boolean(puck.steps.arrayFields?.note.contentEditable), false);
  assert.equal("tags" in puck, false, "an array of plain strings has no dock control yet");
  const described = byName(describeFields(puck as never));
  assert.deepEqual(
    ["heading", "body", "caption", "ctaHref", "heroImage", "tone", "featured", "count", "steps"].map((name) => described[name].kind),
    ["text", "textarea", "text", "link", "image", "select", "boolean", "number", "list"],
  );
});

test("an agent section's brand choices are pick-lists from this brand, never typed or edited in place", () => {
  const puck = puckFieldsFromJsonSchema(
    {
      type: "object",
      properties: {
        id: { type: "string" },
        surface: { type: "string", edit: "inline" },
        heroSurface: { type: "string" },
        look: { type: "string" },
        ctaLook: { type: "string", edit: "inline" },
        cardLook: { type: "string" },
        alt: { type: "string", edit: "inline" },
        imageAlt: { type: "string", edit: "inline" },
        buttonHref: { type: "string", edit: "inline" },
        heroImage: { type: "string", edit: "inline" },
        cards: { type: "array", items: { type: "object", properties: { title: { type: "string", edit: "inline" }, cardLook: { type: "string" } } } },
      },
    },
    brand,
  ) as Record<string, { type: string; contentEditable?: boolean; options?: { label: string; value: unknown }[]; arrayFields?: Record<string, { type: string; options?: unknown[] }> }>;
  const surfaces = surfaceChoices(brand).map((choice) => ({ label: choice.label, value: choice.value }));
  const buttonStyles = buttonLookOptions(brand);
  const cardStyles = [{ label: "Standard", value: "" }, ...cardLooks(brand).map((look) => ({ label: look.label, value: look.name }))];
  assert.ok(cardStyles.length > 1, "Garner's kit records card styles");
  for (const name of ["surface", "heroSurface"]) assert.deepEqual([puck[name].type, puck[name].options], ["select", surfaces], name);
  for (const name of ["look", "ctaLook"]) assert.deepEqual([puck[name].type, puck[name].options], ["select", buttonStyles], name);
  assert.deepEqual([puck.cardLook.type, puck.cardLook.options], ["select", cardStyles]);
  assert.deepEqual([puck.cards.arrayFields?.cardLook.type, puck.cards.arrayFields?.cardLook.options], ["select", cardStyles]);
  for (const name of ["surface", "ctaLook", "alt", "imageAlt", "buttonHref", "heroImage"]) {
    assert.equal(Boolean(puck[name].contentEditable), false, `a marked ${name} is still not edited in place`);
  }
  assert.equal(puck.heroImage.type, "custom");
  const described = byName(describeFields(puck as never));
  assert.deepEqual([described.surface.kind, described.surface.options], ["select", surfaces]);
  assert.deepEqual([described.ctaLook.kind, described.ctaLook.options], ["select", buttonStyles]);
  assert.deepEqual([described.cardLook.kind, described.cardLook.options], ["select", cardStyles]);
  assert.deepEqual([described.alt.kind, described.buttonHref.kind], ["text", "link"]);
});

test("the page config gives an agent section its fields with this brand's choices", () => {
  const section = {
    name: "QuoteBlock",
    module: { schema: { safeParse: () => ({ success: true }) }, render: () => null },
    propsSchema: { type: "object", properties: { id: { type: "string" }, surface: { type: "string" }, quote: { type: "string", edit: "inline" } } },
  };
  const withSection = buildPageConfig(brand, null, [section as never]);
  const fields = byName(fieldsForComponent(withSection, brand, "QuoteBlock", { id: "q" }));
  assert.equal(fields.surface.kind, "select");
  assert.deepEqual(fields.surface.options, surfaceChoices(brand).map((choice) => ({ label: choice.label, value: choice.value })));
  assert.equal(fields.quote.kind, "textarea");
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
