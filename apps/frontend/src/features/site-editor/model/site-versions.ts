import type { SiteVersion } from "./site-wire";

/** The action menu's designed rows (plan Q4 (a)): the newest is "Current version", the rest
 * "Version N". Who made a version and when is not shown until there is a design for it. */
export function siteVersionOptions(versions: readonly SiteVersion[]): { id: string; label: string }[] {
  return versions.map((version, index) => ({
    id: version.batchId,
    label: index === 0 ? "Current version" : `Version ${version.version}`,
  }));
}
