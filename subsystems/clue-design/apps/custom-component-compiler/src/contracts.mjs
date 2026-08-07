import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const packageJson = require("../package.json");

export const PROTOCOL_VERSION = 1;
export const COMPILER_VERSION = "lumen-custom-component-compiler/1";

export const ALLOWED_BARE_IMPORTS = new Set([
  "react",
  "react/jsx-runtime",
  "react/jsx-dev-runtime",
  "@visx/shape",
  "@visx/curve",
  "@visx/group",
  "@visx/scale",
  "motion/react",
  "gsap",
  "@gsap/react",
]);
export const CURATED_PACKAGE_VERSIONS = Object.freeze(
  Object.fromEntries(
    [
      "react",
      "@visx/shape",
      "@visx/curve",
      "@visx/group",
      "@visx/scale",
      "motion",
      "gsap",
      "@gsap/react",
    ].map((name) => [name, packageJson.dependencies[name]]),
  ),
);
export const TOOLCHAIN_PACKAGE_VERSIONS = Object.freeze(
  Object.fromEntries(
    ["typescript", "esbuild", "tailwindcss", "postcss", "react-dom"].map(
      (name) => [name, packageJson.dependencies[name]],
    ),
  ),
);

export const SOURCE_EXTENSIONS = new Set([".ts", ".tsx", ".js", ".jsx"]);
export const MAX_FILE_COUNT = 32;
export const MAX_FILE_BYTES = 256 * 1024;
export const MAX_SOURCE_BYTES = 1024 * 1024;
export const MAX_FIRST_FRAME_BYTES = 256 * 1024;
export const RENDER_TIMEOUT_MS = 500;

const SLUG_PATTERN =
  /^(?:[a-z0-9]|[a-z0-9](?:[a-z0-9]|-(?!-)){0,62}[a-z0-9])$/;

export function slugIsValid(slug) {
  return typeof slug === "string" && SLUG_PATTERN.test(slug);
}

export function sourcePathIsValid(filePath) {
  if (
    typeof filePath !== "string" ||
    filePath.length === 0 ||
    filePath.length > 240 ||
    filePath.includes("\\") ||
    filePath.includes("\0") ||
    path.posix.isAbsolute(filePath)
  ) {
    return false;
  }
  const normalized = path.posix.normalize(filePath);
  return (
    normalized === filePath &&
    normalized !== "." &&
    normalized !== ".." &&
    !normalized.startsWith("../") &&
    SOURCE_EXTENSIONS.has(path.posix.extname(normalized))
  );
}

export function diagnostic({
  code,
  severity = "error",
  category,
  message,
  file = null,
  line = null,
  column = null,
}) {
  return { code, severity, category, message, file, line, column };
}

export function sortDiagnostics(diagnostics) {
  return [...diagnostics].sort((left, right) => {
    const leftKey = [
      left.severity === "error" ? 0 : 1,
      left.file ?? "",
      left.line ?? 0,
      left.column ?? 0,
      left.code,
      left.message,
    ];
    const rightKey = [
      right.severity === "error" ? 0 : 1,
      right.file ?? "",
      right.line ?? 0,
      right.column ?? 0,
      right.code,
      right.message,
    ];
    return JSON.stringify(leftKey).localeCompare(JSON.stringify(rightKey));
  });
}

export function hasErrors(diagnostics) {
  return diagnostics.some((item) => item.severity === "error");
}
