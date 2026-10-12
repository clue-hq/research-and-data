import type { WebElementAddress } from "@/features/design-editor/engine/webBridge";

/** C7 / Lane A3: a site annotation's `design_node` object id — `site:<route>#<componentId>`, plus
 * an optional `.<propName>`; the shell's header and footer are `site:shell#header|footer`. */
export function siteObjectId(target: string, componentId: string, prop?: string): string {
  const base = `site:${target}#${componentId}`;
  return prop ? `${base}.${prop}` : base;
}

/** The web lane's reducer is address-agnostic: a site address carries its whole object id as the
 * `nodeId` and no `path`, so `addressObjectId` returns exactly the A3 id and `addressKey` stays
 * unique. `tag` is display-only. */
export function siteAnnotationAddress(target: string, componentId: string, componentType: string): WebElementAddress {
  return { nodeId: siteObjectId(target, componentId), tag: componentType };
}
