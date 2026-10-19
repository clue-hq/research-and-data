// Editor-only (plan 6, ruling R8): the labels of a header's menu are typed in place on the canvas, in a
// template (CloneEditor) and in the fallback header (MenuLabels) alike. A page's label is written to the
// header's `menuLabels` by page, an extra link's to its `menuExtra` entry. Labels are plain text, written
// once when the marketer leaves the label (a write redraws the menu, which would take the caret away).
import { MENU_LABEL_ATTR, MENU_SOURCE_ATTR } from "../clone";

/** The header's props with one menu label written: `page:/<route>` or `extra:<n>` (MENU_SOURCE_ATTR).
 * An emptied page label drops its entry (the page's own name shows again); an emptied extra label, or
 * an extra that does not exist, writes nothing (null). */
export function writeMenuLabel(props: Record<string, unknown>, source: string, label: string): Record<string, unknown> | null {
  const text = label.replace(/\s+/g, " ").trim();
  if (source.startsWith("page:")) {
    const route = source.slice("page:".length);
    const key = route === "/" ? "_home" : route.slice(1);
    const labels = { ...((props.menuLabels as Record<string, string> | undefined) ?? {}) };
    if (text) labels[key] = text;
    else delete labels[key];
    const next: Record<string, unknown> = { ...props, menuLabels: labels };
    if (!Object.keys(labels).length) delete next.menuLabels;
    return next;
  }
  const index = Number(/^extra:(\d+)$/.exec(source)?.[1] ?? NaN);
  const extras = (props.menuExtra as { label: string; href: string; newTab?: boolean }[] | undefined) ?? [];
  if (!text || !Number.isInteger(index) || !extras[index]) return null;
  return { ...props, menuExtra: extras.map((extra, at) => (at === index ? { ...extra, label: text } : extra)) };
}

/** Makes every menu label under `root` editable in place; `write(source, label)` is called when the
 * marketer leaves a label they changed. Returns the cleanup. */
export function markMenuLabels(root: HTMLElement, write: (source: string, label: string) => void): () => void {
  const cleanups: (() => void)[] = [];
  for (const item of root.querySelectorAll<HTMLElement>(`[${MENU_SOURCE_ATTR}]`)) {
    const source = item.getAttribute(MENU_SOURCE_ATTR) ?? "";
    const label = item.hasAttribute(MENU_LABEL_ATTR) ? item : (item.querySelector<HTMLElement>(`[${MENU_LABEL_ATTR}]`) ?? item);
    label.setAttribute("contenteditable", "true");
    // Puck lets pointer events through only to elements marked as its overlay portals (CloneEditor).
    label.setAttribute("data-puck-overlay-portal", "true");
    let before = "";
    const onFocus = () => {
      before = (label.textContent ?? "").replace(/\s+/g, " ").trim();
    };
    const onBlur = () => {
      const text = (label.textContent ?? "").replace(/\s+/g, " ").trim();
      if (text !== before) write(source, text);
      before = text;
    };
    // Enter leaves the label (a menu label is one line).
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      label.blur();
    };
    const stop = (event: Event) => event.stopPropagation();
    label.addEventListener("focus", onFocus);
    label.addEventListener("blur", onBlur);
    label.addEventListener("keydown", onKey);
    label.addEventListener("click", stop);
    label.addEventListener("pointerdown", stop);
    cleanups.push(() => {
      label.removeAttribute("contenteditable");
      label.removeAttribute("data-puck-overlay-portal");
      label.removeEventListener("focus", onFocus);
      label.removeEventListener("blur", onBlur);
      label.removeEventListener("keydown", onKey);
      label.removeEventListener("click", stop);
      label.removeEventListener("pointerdown", stop);
    });
  }
  return () => cleanups.forEach((cleanup) => cleanup());
}
