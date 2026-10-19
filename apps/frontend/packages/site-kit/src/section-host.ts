// What an agent section may import, decided once (review finding K2-1). A compiled section keeps
// three imports: react, react/jsx-runtime and zod. Every host — the hardened render page, the editor
// frame and the published page — hands over the SAME copy of each library through a shim that
// re-exports every name the library has, and the write check refuses a named import the library
// does not have. Before this, the editor handed over a hand-written short list, so a section could
// publish fine and then fail to open in the editor.
import * as React from "react";
import * as jsxRuntime from "react/jsx-runtime";
import * as zod from "zod";

export const HOST_SPECIFIERS = ["react", "react/jsx-runtime", "zod"] as const;
export type HostSpecifier = (typeof HOST_SPECIFIERS)[number];

const RESERVED = new Set(
  ("break case catch class const continue debugger default delete do else enum export extends false finally for " +
    "function if import in instanceof new null return super switch this throw true try typeof var void while with " +
    "yield let static implements interface package private protected public await").split(" "),
);
const IDENTIFIER = /^[A-Za-z_$][\w$]*$/;

export function hostModules(): Record<HostSpecifier, Record<string, unknown>> {
  return {
    react: React as unknown as Record<string, unknown>,
    "react/jsx-runtime": jsxRuntime as unknown as Record<string, unknown>,
    zod: zod as unknown as Record<string, unknown>,
  };
}

/** Every name a shim re-exports from a library: all of its exports a module can bind by name. */
export function hostExportNames(module: Record<string, unknown>): string[] {
  return Object.keys(module).filter((name) => name !== "default" && IDENTIFIER.test(name) && !RESERVED.has(name)).sort();
}

/** The ES module that stands in for `specifier`: it re-exports the host's own copy, put on
 * globalThis.__clueSectionHost by whoever loads sections, before any section is imported. */
export function shimSource(specifier: HostSpecifier, names: readonly string[]): string {
  return [
    `const m = globalThis.__clueSectionHost && globalThis.__clueSectionHost[${JSON.stringify(specifier)}];`,
    `if (!m) throw new Error(${JSON.stringify(`The page has not shared ${specifier} with agent sections.`)});`,
    "export default m.default ?? m;",
    ...(names.length ? [`export const { ${names.join(", ")} } = m;`] : []),
    "",
  ].join("\n");
}

const NAMED_IMPORT = /import\s*\{([^}]*)\}\s*from\s*["'](react\/jsx-runtime|react|zod)["']/g;

/** One message per name a compiled module imports from a host library that the library lacks. */
export function foreignHostImports(moduleJs: string): string[] {
  const modules = hostModules();
  const errors: string[] = [];
  for (const match of moduleJs.matchAll(NAMED_IMPORT)) {
    const specifier = match[2] as HostSpecifier;
    const known = new Set(hostExportNames(modules[specifier]));
    for (const part of match[1].split(",")) {
      const name = part.trim().split(/\s+as\s+/)[0]?.trim();
      if (name && !known.has(name)) errors.push(`the module imports "${name}" from "${specifier}", which ${specifier} does not export`);
    }
  }
  return errors;
}
