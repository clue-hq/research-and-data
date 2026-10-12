import type { EditorMode, SiteGeometry } from "@clue/site-kit/editor-protocol";

export type ClickAction =
  | { kind: "navigate"; href: string }
  | { kind: "shell"; part: "header" | "footer"; element: Element }
  | { kind: "component"; componentId: string; element: Element }
  | { kind: "none" };

function asElement(target: EventTarget | null): Element | null {
  const node = target as (Partial<Element> & { parentElement?: Element | null }) | null;
  if (!node) return null;
  if (typeof node.closest === "function") return node as Element;
  return node.parentElement ?? null; // a text node
}

/**
 * What one click on the canvas means. Preview: a link switches page (the frame never navigates
 * itself — `preventDefault` — except to an in-page "#anchor"). Edit: a click on the header/footer
 * selects the shell, a click on a section reports it for the comment box, and no link is followed.
 */
export function clickIntent(target: EventTarget | null, mode: EditorMode): { action: ClickAction; preventDefault: boolean } {
  const element = asElement(target);
  if (!element) return { action: { kind: "none" }, preventDefault: false };
  const anchor = element.closest("a[href]");
  const href = anchor?.getAttribute("href") ?? null;
  const inPage = href !== null && href.startsWith("#");
  const preventDefault = anchor !== null && (mode === "edit" || !inPage);
  if (mode !== "edit") {
    return { action: href !== null && !inPage ? { href, kind: "navigate" } : { kind: "none" }, preventDefault };
  }
  const shell = element.closest(".brand-root > header, .brand-root > footer");
  if (shell) {
    return {
      action: { element: shell, kind: "shell", part: shell.tagName.toLowerCase() === "header" ? "header" : "footer" },
      preventDefault,
    };
  }
  const component = element.closest("[data-puck-component]");
  if (component) {
    return {
      action: { componentId: component.getAttribute("data-puck-component") ?? "", element: component, kind: "component" },
      preventDefault,
    };
  }
  return { action: { kind: "none" }, preventDefault };
}

/** The web bridge's geometry shape: the element's box in viewport and in document coordinates. */
export function rectOf(element: Element, scroll: { x: number; y: number }): SiteGeometry {
  const box = element.getBoundingClientRect();
  const viewport = {
    bottom: box.bottom,
    height: box.height,
    left: box.left,
    right: box.right,
    top: box.top,
    width: box.width,
    x: box.x,
    y: box.y,
  };
  return {
    document: {
      ...viewport,
      bottom: box.bottom + scroll.y,
      left: box.left + scroll.x,
      right: box.right + scroll.x,
      top: box.top + scroll.y,
      x: box.x + scroll.x,
      y: box.y + scroll.y,
    },
    viewport,
  };
}
