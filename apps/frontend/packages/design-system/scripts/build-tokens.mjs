import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const sourceRoot = join(packageRoot, "source", "figma");
const productSourcePath = join(
  packageRoot,
  "source",
  "product",
  "product-tokens.json",
);
const outputPath = join(packageRoot, "generated", "tokens.css");

function readCollection(name) {
  return JSON.parse(readFileSync(join(sourceRoot, `${name}.json`), "utf8"));
}

const primitives = readCollection("primitives");
const tokens = readCollection("tokens");
const typography = readCollection("typography");
const product = JSON.parse(readFileSync(productSourcePath, "utf8"));

function validateProductTokens(value) {
  if (!value || value.schemaVersion !== 1 || !Array.isArray(value.tokens)) {
    throw new Error("Invalid source/product/product-tokens.json schema");
  }

  const names = new Set();

  for (const token of value.tokens) {
    if (!token.name || token.value === undefined) {
      throw new Error("Every product token requires a name and value");
    }

    if (names.has(token.name)) {
      throw new Error(`Duplicate product token: ${token.name}`);
    }

    names.add(token.name);
  }
}

validateProductTokens(product);

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

function modeValue(variable) {
  return Object.values(variable.valuesByMode)[0];
}

function fontWeight(value) {
  return (
    {
      Light: 300,
      Regular: 400,
      Medium: 500,
      "Semi Bold": 600,
      Bold: 700,
    }[value] ?? value
  );
}

function cssValue(variable, value) {
  if (value && value.type === "VARIABLE_ALIAS") {
    return `var(${cssName(value.name)})`;
  }

  if (value && value.hex) {
    return value.hex;
  }

  if (variable.resolvedType === "STRING") {
    if (variable.name.endsWith("/font-family")) {
      return JSON.stringify(String(value).replace("Satoshi Variable", "Satoshi"));
    }

    if (variable.name.endsWith("/font-weight")) {
      return String(fontWeight(value));
    }

    return JSON.stringify(value);
  }

  if (
    variable.resolvedType === "FLOAT" &&
    (/font-size$/.test(variable.name) || /line-height$/.test(variable.name))
  ) {
    return `${value}px`;
  }

  return String(value);
}

function section(title, variables) {
  return [
    `  /* ${title} */`,
    ...variables.map(
      (variable) =>
        `  ${cssName(variable.name)}: ${cssValue(variable, modeValue(variable))};`,
    ),
  ].join("\n");
}

function productCssValue(token) {
  if (token.kind === "font-family") {
    return `"${token.value}", Arial, sans-serif`;
  }

  if (token.unit) {
    return `${token.value}${token.unit}`;
  }

  return String(token.value);
}

function productSection(tokens) {
  return [
    "  /* Product semantics verified against approved Dev Mode components. */",
    ...tokens.map(
      (token) =>
        `  --clue-ds-product-${slug(token.name)}: ${productCssValue(token)};`,
    ),
  ].join("\n");
}

const css = [
  "/*",
  " * Generated from the Clue Design System Figma library.",
  " * Source: Gqz4ROcgy5sZ4HMWsLpOVf",
  " * Do not hand-edit values; regenerate from source/figma and source/product.",
  " */",
  "",
  ":root {",
  section("Primitives", primitives.variables),
  "",
  section("Semantic tokens", tokens.variables),
  "",
  section("Typography", typography.variables),
  "",
  productSection(product.tokens),
  "",
  "  /* Effect-style bridge used by the existing application shell. */",
  "  --clue-ds-shadow-card-subtle: 0 1px 2px rgb(0 0 0 / 6.67%);",
  "}",
  "",
].join("\n");

writeFileSync(outputPath, css);
console.log(`Built ${outputPath}`);
