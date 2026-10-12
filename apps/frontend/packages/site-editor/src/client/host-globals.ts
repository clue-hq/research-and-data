import * as React from "react";
import * as jsxRuntime from "react/jsx-runtime";
import * as zod from "zod";

declare global {
  // eslint-disable-next-line no-var
  var __clueSectionHost: Record<string, unknown> | undefined;
}

/** A compiled agent section keeps three imports: react, react/jsx-runtime and zod. The page's import
 * map points each at a shim on this origin (/shims/*.mjs) that re-exports the copy put here, so a
 * section runs on the editor's one React (hooks and context work) and the editor's zod. */
export function installSectionHost(): void {
  globalThis.__clueSectionHost = { react: React, "react/jsx-runtime": jsxRuntime, zod };
}
