import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const lobeIconsRoot = dirname(
  require.resolve("@lobehub/icons-static-svg/package.json"),
);
const iconifyLogosPath = require.resolve("@iconify-json/logos/icons.json");
const simpleIconsPath = require.resolve("@iconify-json/simple-icons/icons.json");
const outputRoot = join(projectRoot, "public", "logos");

const lobeIcons = {
  "anthropic.svg": "anthropic.svg",
  "openai.svg": "openai.svg",
  "cohere.svg": "cohere-color.svg",
  "perplexity.svg": "perplexity-color.svg",
  "mistral.svg": "mistral-color.svg",
  "hugging-face.svg": "huggingface-color.svg",
  "snowflake.svg": "snowflake-color.svg",
  "antigravity.svg": "antigravity-color.svg",
  "google-deepmind.svg": "google-color.svg",
  "midjourney.svg": "midjourney.svg",
  "cursor.svg": "cursor.svg",
};

await mkdir(outputRoot, { recursive: true });

for (const [outputName, sourceName] of Object.entries(lobeIcons)) {
  await copyFile(
    join(lobeIconsRoot, "icons", sourceName),
    join(outputRoot, outputName),
  );
}

const iconifyLogos = JSON.parse(await readFile(iconifyLogosPath, "utf8"));
const iconifyLogoExports = {
  "airtable.svg": ["airtable", "Airtable"],
  "contentful.svg": ["contentful", "Contentful"],
  "sanity.svg": ["sanity", "Sanity"],
  "slack.svg": ["slack-icon", "Slack"],
  "webflow.svg": ["webflow", "Webflow"],
  "marvel.svg": ["marvel", "Marvel"],
};

for (const [outputName, [iconName, title]] of Object.entries(
  iconifyLogoExports,
)) {
  const icon = iconifyLogos.icons[iconName];
  const height = icon.height ?? iconifyLogos.height;
  const width = icon.width ?? iconifyLogos.width;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}"><title>${title}</title>${icon.body}</svg>\n`;
  await writeFile(join(outputRoot, outputName), svg, "utf8");
}

const simpleIcons = JSON.parse(await readFile(simpleIconsPath, "utf8"));
const simpleIconExports = {
  "ada.svg": ["ada", "Ada", "#1c2028"],
  "godaddy.svg": ["godaddy", "GoDaddy", "#00a4a6"],
  "wikipedia.svg": ["wikipedia", "Wikipedia", "#1c2028"],
};

for (const [outputName, [iconName, title, color]] of Object.entries(
  simpleIconExports,
)) {
  const icon = simpleIcons.icons[iconName];
  const height = icon.height ?? simpleIcons.height;
  const width = icon.width ?? simpleIcons.width;
  const body = icon.body.replaceAll("currentColor", color);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}"><title>${title}</title>${body}</svg>\n`;
  await writeFile(join(outputRoot, outputName), svg, "utf8");
}

console.log(
  `Synced ${
    Object.keys(lobeIcons).length +
    Object.keys(iconifyLogoExports).length +
    Object.keys(simpleIconExports).length
  } library-backed brand assets.`,
);
