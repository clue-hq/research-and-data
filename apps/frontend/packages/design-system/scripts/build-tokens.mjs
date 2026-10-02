import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const sourceRoot = join(packageRoot, "source", "production");
const componentsRoot = join(sourceRoot, "components");
const outputPath = join(packageRoot, "generated", "tokens.css");

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

const manifest = readJson(join(sourceRoot, "manifest.json"));
const design = readJson(join(sourceRoot, "variables.json"));
const application = readJson(join(sourceRoot, "application.json"));
const components = readdirSync(componentsRoot)
  .filter((name) => name.endsWith(".json"))
  .sort()
  .map((name) => readJson(join(componentsRoot, name)));

const scaleSteps = [25, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];

function slug(name) {
  return name
    .replace(/([a-z0-9])([A-Z])/g, "$1-$2")
    .replace(/[^a-zA-Z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .toLowerCase();
}

function cssName(name) {
  return `--clue-ds-${slug(name)}`;
}

function runtimeCssName(name) {
  return `--clue-ds-product-${slug(name)}`;
}

function withAlpha([hex, alpha]) {
  const suffix = Math.round(alpha * 255)
    .toString(16)
    .padStart(2, "0")
    .toUpperCase();
  return `${hex}${suffix}`;
}

function primitiveEntries() {
  const entries = [["color/primitives/White", design.primitives.White]];

  for (const [group, values] of Object.entries(design.primitives)) {
    if (group === "White" || group === "badge") continue;
    if (!Array.isArray(values) || values.length !== scaleSteps.length) {
      throw new Error(`Primitive scale ${group} must contain 12 values`);
    }
    values.forEach((value, index) => {
      entries.push([
        `color/primitives/${group}/${scaleSteps[index]}`,
        Array.isArray(value) ? withAlpha(value) : value,
      ]);
    });
  }

  for (const [name, value] of Object.entries(design.primitives.badge)) {
    entries.push([
      `color/badge/${name}`,
      value?.alias
        ? `var(${cssName(`color/primitives/${value.alias}`)})`
        : Array.isArray(value)
          ? withAlpha(value)
          : value,
    ]);
  }

  return entries;
}

function tokenEntries() {
  return Object.entries(design.tokens).map(([name, target]) => [
    name,
    `var(${cssName(target)})`,
  ]);
}

function fontWeight(value) {
  return {
    Light: 300,
    Regular: 400,
    Italic: 400,
    Medium: 500,
    "Semi Bold": 600,
    Bold: 700,
  }[value] ?? value;
}

function typographyEntries() {
  return design.typography.flatMap((style) => [
    [`${style.name}/font-family`, `"${style.family.replace("Satoshi Variable", "Satoshi")}", Arial, sans-serif`],
    [`${style.name}/font-weight`, fontWeight(style.weight)],
    [`${style.name}/font-size`, `${style.size}px`],
    [`${style.name}/line-height`, `${style.lineHeight}px`],
  ]);
}

function runtimeValue(token) {
  if (token.kind === "font-family") {
    return `"${token.value}", Arial, sans-serif`;
  }
  if (token.unit) return `${token.value}${token.unit}`;
  return String(token.value);
}

function runtimeEntries() {
  return [
    ...application.tokens,
    ...components.flatMap((component) => component.tokens),
  ].map((token) => [token.name, runtimeValue(token)]);
}

function validateSource() {
  if (manifest.schemaVersion !== 2 || design.schemaVersion !== 2) {
    throw new Error("The resolved production design-system source is out of date");
  }

  const sourceKeys = new Set(manifest.sources.map((source) => source.fileKey));
  for (const key of ["NcLl2r0dzVDN28xAQCwvM1", "Gqz4ROcgy5sZ4HMWsLpOVf"]) {
    if (!sourceKeys.has(key)) throw new Error(`Missing required Figma source ${key}`);
  }

  const primitiveCount = primitiveEntries().length;
  const typographyNames = new Set(design.typography.map((style) => style.name));
  const textStyleIdsAreValid = design.typography.every(
    (style) => /^S:[a-f0-9]{40}$/.test(style.styleId),
  );
  if (
    primitiveCount !== manifest.collections.Primitives
    || Object.keys(design.tokens).length !== manifest.collections.Tokens
    || design.typography.filter((style) => style.name !== "typography/chain-of-thought").length * 4 !== manifest.collections.Typography
    || design.typography.length !== manifest.textStyles
    || typographyNames.size !== design.typography.length
    || !textStyleIdsAreValid
  ) {
    throw new Error("Resolved Figma collection counts do not match the manifest");
  }

  if (!Array.isArray(application.tokens) || application.schemaVersion !== 1) {
    throw new Error("Invalid production application token contract");
  }

  for (const component of components) {
    if (component.schemaVersion !== 1 || !component.component || !Array.isArray(component.tokens)) {
      throw new Error("Invalid production component token contract");
    }
  }
}

function renderSection(title, entries, nameFor = cssName) {
  return [
    `  /* ${title} */`,
    ...entries.map(([name, value]) => `  ${nameFor(name)}: ${value};`),
  ].join("\n");
}

function validateUniqueDefinitions(css) {
  const definitions = [...css.matchAll(/(?:^|\n)\s*(--clue-ds-[\w-]+)\s*:/g)].map((match) => match[1]);
  const duplicates = definitions.filter((name, index) => definitions.indexOf(name) !== index);
  if (duplicates.length > 0) {
    throw new Error(`Duplicate generated token definitions: ${[...new Set(duplicates)].join(", ")}`);
  }
}

function validateReferences(css) {
  const definitions = new Set(
    [...css.matchAll(/(?:^|\n)\s*(--clue-ds-[\w-]+)\s*:/g)].map((match) => match[1]),
  );
  const references = new Set(
    [...css.matchAll(/var\((--clue-ds-[\w-]+)\)/g)].map((match) => match[1]),
  );
  const missing = [...references].filter((name) => !definitions.has(name));
  if (missing.length > 0) {
    throw new Error(`Generated CSS references missing tokens: ${missing.join(", ")}`);
  }
}

validateSource();

const css = [
  "/*",
  " * Generated from the resolved production Clue design system.",
  " * Product source: NcLl2r0dzVDN28xAQCwvM1",
  " * Component/token source: Gqz4ROcgy5sZ4HMWsLpOVf",
  " * Do not hand-edit. Update source/production and regenerate.",
  " */",
  "",
  ":root {",
  renderSection("Primitives", primitiveEntries()),
  "",
  renderSection("Semantic tokens", tokenEntries()),
  "",
  renderSection("Published typography", typographyEntries()),
  "",
  renderSection(
    "Canonical application and component contracts",
    runtimeEntries(),
    runtimeCssName,
  ),
  "",
  "  /* Published effect style used by current cards. */",
  "  --clue-ds-shadow-card-subtle: 0 1px 2px rgb(0 0 0 / 6.67%);",
  "}",
  "",
].join("\n");

validateUniqueDefinitions(css);
validateReferences(css);
writeFileSync(outputPath, css);
console.log(`Built ${outputPath}`);
