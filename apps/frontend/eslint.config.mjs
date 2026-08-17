import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: [
      "src/components/**/*.tsx",
      "src/features/**/components/**/*.tsx",
    ],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: [
                "**/data/**",
                "**/*.fixture",
                "**/*.repository",
              ],
              message:
                "Presentation components must receive typed props and must not import repositories or fixtures.",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["src/app/**/*.tsx"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/*.fixture"],
              message:
                "Routes must use repositories; fixture selection belongs inside data adapters.",
            },
          ],
        },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Generated vendor assets (scripts/copy-design-vendor.mjs) — third-party
    // minified bundles, not lintable source.
    "public/vendor/**",
  ]),
]);

export default eslintConfig;
