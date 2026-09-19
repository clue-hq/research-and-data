import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

/**
 * The catalog refresh signal is mounted ONCE, in the protected layout.
 *
 * Spec §2.5: every project mutation calls `invalidate()` so the sidebar and any
 * open workspace refetch. That only holds if writer and reader share one
 * provider. Mounted inside `ApplicationShell` it was one provider per shell
 * MOUNT — and several screens render their own `ApplicationShell` (artifacts,
 * accounts, brand-context, and the lifted projects directory/home), so an
 * invalidate on one side of that boundary reached nothing on the other.
 *
 * A file-text contract, in the repo's existing style (`account-ui-contract`):
 * the placement is a JSX tree fact with no runtime seam to call.
 */

const read = (relative: string) =>
  readFileSync(new URL(relative, import.meta.url), "utf8");

test("the protected layout mounts the one catalog-invalidation provider", () => {
  const layout = read("../../../app/(protected)/layout.tsx");
  assert.match(
    layout,
    /import \{ ProjectCatalogInvalidationProvider \} from "@\/features\/projects\/model\/project-catalog-invalidation";/,
  );
  assert.match(layout, /<ProjectCatalogInvalidationProvider>/);
  assert.match(layout, /<\/ProjectCatalogInvalidationProvider>/);
  // Inside the transport provider, above every ApplicationShell mount.
  assert.ok(
    layout.indexOf("<ProjectsTransportProvider") <
      layout.indexOf("<ProjectCatalogInvalidationProvider>"),
  );
  assert.ok(
    layout.indexOf("<ProjectCatalogInvalidationProvider>") <
      layout.indexOf("<ProjectApplicationShell>"),
  );
});

test("ApplicationShell does not mount a second, competing provider", () => {
  assert.doesNotMatch(
    read("../../../components/shell/application-shell.tsx"),
    /ProjectCatalogInvalidationProvider/,
  );
});
