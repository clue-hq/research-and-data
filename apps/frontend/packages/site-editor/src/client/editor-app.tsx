import { useEffect, useMemo, useSyncExternalStore } from "react";
import { Puck, createUsePuck, useGetPuck, type Config, type Data, type Permissions, type Viewports } from "@puckeditor/core";
import { RICH_PROPS, RICH_PROPS_NO_LINKS, cloneButtonAt, cloneLinkAt, imageSourcesOf, ownLinkSource, pageMenuLink, richSourceOf, siteMenuPages, type BrandData } from "@clue/site-kit";
import { richFromDom } from "@clue/site-kit/editor";
import { normalizeRich } from "@clue/site-kit/rich";
import type { ElementSelection, LabelSource, LinkSource, RichSource } from "@clue/site-kit/editor-protocol";
import { acceptAppMessage, frameToApp } from "@clue/site-kit/editor-protocol";
import { canonicalJson, componentEntry, componentProps } from "@clue/site-kit/editor-site";
import { SHELL_TARGET, isShellId } from "@clue/site-kit/site-document";
import type { BootContext } from "./boot";
import { buildPageConfig } from "./config";
import {
  arrangeOf,
  buttonAround,
  buttonLabelOf,
  clickIntent,
  computedBox,
  computedContainer,
  computedImage,
  listedSummary,
  sectionBoxOf,
  computedTypography,
  cssColorToHex,
  elementKeyAt,
  elementSelection,
  findKeyedElement,
  inspectableElementsIn,
  isButtonElement,
  rangeAt,
  rectOf,
  selectionOffsets,
  textElementAround,
  wordCount, sizeScaleAt,
} from "./dom";
import { fieldsForComponent } from "./fields";
import { FrameController, editorPage } from "./frame-controller";
import { frameKeyAction } from "./keys";
import { browserSectionDeps, loadSections } from "./sections";

const usePuck = createUsePuck();
// Insert, delete, duplicate and drag wait for the founder's designs (C13); in-place editing stays on.
const PERMISSIONS: Partial<Permissions> = { delete: false, drag: false, duplicate: false, edit: true, insert: false };
const VIEWPORTS: Viewports = [{ height: "auto", label: "Page", width: "100%" }];
const ELEMENT_SELECTED = "data-clue-el-selected";
const ELEMENT_HOVERED = "data-clue-el-hovered";

/** Where a selection's elements live on the canvas: its Puck item (the header and footer are items
 * too: plan 6). */
function selectionScope(_target: string, componentId: string): Element | null {
  return document.querySelector(`[data-puck-component="${CSS.escape(componentId)}"]`);
}

/** Marks an element's canvas outline. A section, and its background (its own outermost box), span the
 * canvas's width, so theirs is drawn inside their edges ("inset", styles.css). */
function markOutline(element: Element, attribute: string, scope: Element | null): void {
  const inset = scope !== null && (element === scope || sectionBoxOf(scope, window)?.outer === element);
  element.setAttribute(attribute, inset ? "inset" : "true");
}

/** Any computed colour as #RRGGBB: rgb() directly, anything else (oklch, color()) through a canvas,
 * which always reads back sRGB pixels. */
let colorCanvas: CanvasRenderingContext2D | null = null;
function toHex(color: string): string | null {
  const direct = cssColorToHex(color);
  if (direct) return direct;
  colorCanvas ??= document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  if (!colorCanvas) return null;
  colorCanvas.clearRect(0, 0, 1, 1);
  colorCanvas.fillStyle = "#000";
  colorCanvas.fillStyle = color;
  colorCanvas.fillRect(0, 0, 1, 1);
  const [r, g, b] = colorCanvas.getImageData(0, 0, 1, 1).data;
  return cssColorToHex(`rgb(${r}, ${g}, ${b})`);
}

/** Which section (or the header or footer, the shell's) an element on the canvas belongs to. */
function placeOf(element: Element): { target: string; componentId: string } | null {
  const component = element.closest("[data-puck-component]")?.getAttribute("data-puck-component");
  if (!component) return null;
  return { componentId: component, target: isShellId(component) ? SHELL_TARGET : "page" };
}

/** Our buttons: the button's key, and the prop its words are stored in (plan 3; the header's: plan 6). */
const OUR_BUTTONS: Record<string, { key: string; words: string }> = {
  FeatureSplit: { key: "button", words: "buttonLabel" },
  CtaBand: { key: "button", words: "buttonLabel" },
  SiteHeader: { key: "cta", words: "ctaLabel" },
};

/** Our components (their rich words are named by RICH_PROPS / RICH_PROPS_NO_LINKS), as opposed to an agent's. */
const isOurs = (type: string) => type in RICH_PROPS || type in RICH_PROPS_NO_LINKS;

const AGENT_LINK = "The agent's section sets this link; ask the agent to change it.";

/** The chosen element as the `selected` message carries it (plan 1's look, plus plan 2's facts). */
function describeElement(controller: FrameController, target: string, componentId: string, element: Element): ElementSelection {
  const described = elementSelection(element, window, toHex);
  const state = controller.getState();
  const key = described.key;
  let rich: RichSource | null = null;
  let link: LinkSource | null = null;
  const anchored = element.tagName === "A" || element.closest("a") !== null;
  // A menu item that is one of the site's pages links where its page is (plan 6, ruling R11).
  const menuItem = element.closest("[data-clue-menu-source]");
  const pageItem = menuItem?.getAttribute("data-clue-menu-source")?.startsWith("page:") ? menuItem : null;
  if (state.site && state.brand) {
    const item = componentEntry(state.site, target, componentId);
    // An extra menu link (`menu._<n>`) is written in the header's `menuExtra`, whatever the header's
    // type (a template's menu is drawn by the renderer, not captured: final review I5).
    const menuKey = menuItem?.getAttribute("data-clue-el") ?? null;
    const extraLink = item && menuItem && !pageItem && menuKey ? ownLinkSource(item.type, menuKey) : null;
    if (pageItem) {
      link = { kind: "fixed", reason: pageMenuLink((pageItem.textContent ?? "").trim()) };
    } else if (extraLink) {
      link = extraLink;
    } else if (item) {
      const props = item.props as Record<string, unknown>;
      if (item.type === "ClonedSection") {
        const clone = state.brand.clones[String(props.fragmentId ?? "")];
        const slot = element.getAttribute("data-lumen-slot");
        if (clone && slot && clone.slots[slot]?.kind === "text") {
          const stored = (props.slots as Record<string, unknown> | undefined)?.[slot];
          rich = typeof stored === "string" ? { prop: `slots.${slot}` } : { fallback: normalizeRich(richFromDom(element)), prop: `slots.${slot}` };
        }
        const found = clone ? cloneLinkAt(clone, key) : null;
        if (found) link = found.slot ? { kind: "slot", slot: found.slot } : { find: found.href, kind: "replacement", shared: found.shared };
      } else {
        const propsSchemaOf = (type: string) => state.sections.find((section) => section.name === type)?.propsSchema;
        rich = richSourceOf({ props, type: item.type }, key, state.brand, propsSchemaOf);
        // An agent's link is a prop of its own the editor cannot name from the element.
        const agent = !isOurs(item.type);
        link = ownLinkSource(item.type, key) ?? (anchored && agent ? { kind: "fixed", reason: AGENT_LINK } : null);
      }
    }
  }
  const anchor = element.tagName === "A" ? element : element.closest("a");
  const shown = anchor?.getAttribute("href") ?? undefined;
  return { ...described, link: link ? { source: link, ...(shown ? { href: shown.slice(0, 2048) } : {}) } : null, rich, words: wordsIn(element) };
}

const AGENT_BUTTON = "The agent's section sets this button's words and link; ask the agent to change them.";
const CLONE_BUTTON_WORDS = "This button's words are copied from the seller's page and have no slot.";

/** The chosen button as the `selected` message carries it (plan 3): its words (key, look, where they
 * are stored as rich text), its box as drawn, where its words and its link are written, and the words
 * highlighted in its label. */
function describeButton(controller: FrameController, target: string, componentId: string, button: Element): ElementSelection {
  const described = elementSelection(button, window, toHex);
  const label = buttonLabelOf(button) ?? button;
  const labelKey = label.getAttribute("data-clue-el") ?? described.key;
  const state = controller.getState();
  const key = described.key;
  let rich: RichSource | null = null;
  let labelSource: LabelSource | null = null;
  let link: LinkSource | null = null;
  if (state.site && state.brand) {
    const item = componentEntry(state.site, target, componentId);
    const props = (item?.props ?? {}) as Record<string, unknown>;
    if (item?.type === "ClonedSection") {
      const clone = state.brand.clones[String(props.fragmentId ?? "")];
      const found = clone ? cloneButtonAt(clone, key) : null;
      if (found?.labelSlot) {
        const stored = (props.slots as Record<string, unknown> | undefined)?.[found.labelSlot];
        rich = typeof stored === "string" ? { prop: `slots.${found.labelSlot}` } : { fallback: normalizeRich(richFromDom(label), { links: false }), prop: `slots.${found.labelSlot}` };
        labelSource = { kind: "slot", slot: found.labelSlot };
      } else {
        labelSource = found?.labelText ? { find: found.labelText, kind: "replacement", shared: found.labelShared } : { kind: "fixed", reason: CLONE_BUTTON_WORDS };
      }
      if (found?.hrefSlot) link = { kind: "slot", slot: found.hrefSlot };
      else if (found?.href) link = { find: found.href, kind: "replacement", shared: found.shared };
    } else if (item && isOurs(item.type)) {
      const button = OUR_BUTTONS[item.type];
      if (button && key === button.key) {
        rich = { prop: button.words };
        labelSource = { kind: "prop", prop: button.words };
      }
      link = ownLinkSource(item.type, key);
    } else if (item) {
      // An agent's button named after the marked prop holding its words (el="cta", label={props.cta})
      // has them written there (ruling R6); otherwise its words are the agent's to change.
      const propsSchemaOf = (type: string) => state.sections.find((section) => section.name === type)?.propsSchema;
      rich = richSourceOf({ props, type: item.type }, key, state.brand, propsSchemaOf);
      labelSource = rich ? { kind: "prop", prop: rich.prop } : { kind: "fixed", reason: AGENT_BUTTON };
      link = { kind: "fixed", reason: AGENT_BUTTON };
    }
  }
  const shown = button.getAttribute("href") ?? undefined;
  return {
    ...described,
    box: computedBox(button, window, toHex),
    kind: "button",
    labelElement: { computed: computedTypography(label, window, toHex), key: labelKey, rich },
    labelSource,
    link: link ? { source: link, ...(shown ? { href: shown.slice(0, 2048) } : {}) } : null,
    rich: null,
    words: wordsIn(label),
  };
}

/** Plan 4: the header's or footer's parts hidden by hand, read from the stored shell (they have no box
 * on the canvas, so the canvas cannot tell). */
function hiddenParts(controller: FrameController, target: string, componentId: string): Set<string> {
  if (target !== SHELL_TARGET || (componentId !== "header" && componentId !== "footer")) return new Set();
  const site = controller.getState().site;
  const edits = ((site ? componentProps(site, target, componentId) : null)?._edits as Record<string, { hidden?: boolean }> | undefined) ?? {};
  return new Set(Object.entries(edits).flatMap(([key, override]) => (override?.hidden === true ? [key] : [])));
}

/** A chosen box or image (plan 4): its summary, its typography (what it passes to its text), and for a
 * box its look as drawn; for an image (plan 5) how it is drawn and where its file and its alt text are
 * written (site-kit's imageSourcesOf, from the stored site). */
function describeBox(
  controller: FrameController,
  target: string,
  componentId: string,
  element: Element,
  item: Parameters<typeof listedSummary>[0],
): ElementSelection {
  const described: ElementSelection = {
    ...listedSummary(item, window),
    computed: computedTypography(element, window, toHex),
    ...(item.kind === "container" ? { container: computedContainer(element, window, toHex) } : {}),
  };
  if (item.kind !== "image") return described;
  const image = computedImage(element, window, toHex);
  const state = controller.getState();
  const entry = state.site ? componentEntry(state.site, target, componentId) : null;
  const type = entry?.type ?? "";
  const props = (entry?.props ?? {}) as Record<string, unknown>;
  const clone = type === "ClonedSection" && state.brand ? (state.brand.clones[String(props.fragmentId ?? "")] ?? null) : null;
  const sources = imageSourcesOf({ clone, key: described.key, media: image.media, props, src: image.src, type });
  return { ...described, altSource: sources.alt, image, imageSource: sources.image };
}

/** Responsive brand type (review finding 3): every typography in the selection carries the brand's
 * size scale where the element is drawn now, so the panel shows and takes sizes as drawn in a
 * narrowed preview. Nothing is added on desktop or for a kit that did not measure its steps. */
function withSizeScale(selection: ElementSelection, element: Element, brand: BrandData | null): ElementSelection {
  const sizeScale = brand ? sizeScaleAt(element, brand, window) : null;
  if (!sizeScale) return selection;
  return {
    ...selection,
    computed: { ...selection.computed, sizeScale },
    ...(selection.words ? { words: { ...selection.words, computed: { ...selection.words.computed, sizeScale } } } : {}),
    ...(selection.labelElement ? { labelElement: { ...selection.labelElement, computed: { ...selection.labelElement.computed, sizeScale } } } : {}),
  };
}

/** The words highlighted inside the element now, or null. */
function wordsIn(element: Element): ElementSelection["words"] {
  const selection = document.getSelection();
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
  const range = selection.getRangeAt(0);
  const offsets = selectionOffsets(element, range);
  if (!offsets || !offsets.text.trim()) return null;
  const first = range.startContainer.nodeType === 1 ? (range.startContainer as Element) : range.startContainer.parentElement;
  return { ...offsets, computed: computedTypography(first ?? element, window, toHex), count: wordCount(offsets.text) };
}

/** After a redraw the browser's highlight is gone: put the kept words back, if their text is still there. */
function highlightKeptWords(controller: FrameController): void {
  const kept = controller.keptWords();
  const selection = controller.getState().selection;
  if (!kept || !selection || selection.elementKey !== kept.key || selection.componentId !== kept.componentId) return;
  const scope = selectionScope(selection.target, selection.componentId);
  const found = scope ? findKeyedElement(scope, kept.key) : null;
  const element = found && isButtonElement(found, window) ? buttonLabelOf(found) : found;
  const current = document.getSelection();
  if (!element || !current) return;
  if (current.rangeCount && !current.isCollapsed && selectionOffsets(element, current.getRangeAt(0))) return;
  const range = rangeAt(element, kept.words.start, kept.words.end);
  if (!range || range.toString() !== kept.words.text) return;
  current.removeAllRanges();
  current.addRange(range);
}

export function EditorApp({ boot }: { boot: BootContext }) {
  const controller = useMemo(
    () =>
      new FrameController({
        loadSections: (links) => loadSections(links, browserSectionDeps()),
        post: (type, payload, documentId) => {
          // Contract 6: always the app's exact origin, never "*".
          window.parent.postMessage(frameToApp(type, payload, { documentId, nonce: boot.nonce }), boot.appOrigin);
        },
      }),
    [boot],
  );
  const state = useSyncExternalStore(controller.subscribe, controller.getState, controller.getState);

  // The canvas half of element selection: the section's text elements and the chosen one, read
  // from the page as drawn now — with, for the chosen one (plan 2), where its rich words and its link
  // are written and the words highlighted in it.
  useEffect(() => {
    controller.attachDescriber((target, componentId, key) => {
      const scope = selectionScope(target, componentId);
      if (!scope) return { element: null, elements: [] };
      const listed = inspectableElementsIn(scope, window, hiddenParts(controller, target, componentId));
      const keyed = key ? findKeyedElement(scope, key) : null;
      const kind = keyed ? listed.find((item) => item.element === keyed)?.kind : undefined;
      // A keyed element Layers does not list (a pass-through wrapper, an empty overlay) is not
      // selectable: the selection is then the section, never a wrapper described as text (review I1).
      const found = keyed && (kind || isButtonElement(keyed, window)) ? keyed : null;
      let element: ElementSelection | null = null;
      if (found) {
        const described =
          isButtonElement(found, window)
            ? describeButton(controller, target, componentId, found)
            : kind === "container" || kind === "image"
              ? describeBox(controller, target, componentId, found, listed.find((item) => item.element === found)!)
              : describeElement(controller, target, componentId, found);
        const arrange = arrangeOf(found, scope);
        element = withSizeScale({ ...described, ...(arrange ? { arrange } : {}) }, found, controller.getState().brand);
      }
      // The section's own outermost box is its background (founder 2026-10-19): its key always rides
      // along, its look only when it is the one asked for.
      const box = sectionBoxOf(scope, window);
      const backgroundKey = box?.outer.getAttribute("data-clue-el") || null;
      return {
        element,
        elements: listed.map((item) => listedSummary(item, window)),
        backgroundKey,
        sectionBox: box && key !== null && key === backgroundKey
          ? {
              inner: { container: computedContainer(box.inner, window, toHex), key: box.inner.getAttribute("data-clue-el") ?? "" },
              outer: { box: computedBox(box.outer, window, toHex), key: box.outer.getAttribute("data-clue-el") ?? "" },
            }
          : null,
      };
    });
    return () => controller.attachDescriber(null);
  }, [controller]);

  // Plan 2: the text the marketer highlights. Read a frame after the browser reports it (it reports
  // every step of a drag), and handed to the controller, which decides what to post.
  useEffect(() => {
    let frame = 0;
    const read = () => {
      frame = 0;
      const selection = document.getSelection();
      if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        controller.selectionChanged(null);
        return;
      }
      const node = selection.getRangeAt(0).commonAncestorContainer;
      // Words highlighted in a button's label select the button (plan 3).
      const element = buttonAround(node, window) ?? textElementAround(node);
      const place = element ? placeOf(element) : null;
      const key = element?.getAttribute("data-clue-el");
      const target = place?.target === SHELL_TARGET ? SHELL_TARGET : controller.getState().route;
      controller.selectionChanged(place && key ? { componentId: place.componentId, key, target } : null);
    };
    const onSelectionChange = () => {
      if (!frame) frame = requestAnimationFrame(read);
    };
    const onAct = () => controller.userActed();
    document.addEventListener("selectionchange", onSelectionChange);
    document.addEventListener("pointerdown", onAct, true);
    document.addEventListener("keydown", onAct, true);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      document.removeEventListener("selectionchange", onSelectionChange);
      document.removeEventListener("pointerdown", onAct, true);
      document.removeEventListener("keydown", onAct, true);
    };
  }, [controller]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const message = acceptAppMessage(
        { data: event.data, origin: event.origin, source: event.source },
        { appOrigin: boot.appOrigin, documentId: controller.getState().documentId, nonce: boot.nonce, parent: window.parent },
      );
      if (message) void controller.receive(message);
    };
    window.addEventListener("message", onMessage);
    controller.announceReady();
    return () => window.removeEventListener("message", onMessage);
  }, [boot, controller]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      const { action, preventDefault } = clickIntent(event.target, controller.getState().mode);
      if (preventDefault) event.preventDefault();
      // The canvas scrolls inside #root (styles.css), never the window.
      const scroller = document.getElementById("root");
      const scroll = { x: scroller?.scrollLeft ?? 0, y: scroller?.scrollTop ?? 0 };
      if (action.kind === "navigate") controller.linkClicked(action.href);
      // The text element the click meant (null: the section itself), named before the section's
      // selection is reported, which then carries it.
      const point = { x: event.clientX, y: event.clientY };
      if (action.kind === "component" && action.componentId) {
        // The header and footer are Puck items addressed as the shell (plan 6, ruling R3).
        const target = isShellId(action.componentId) ? SHELL_TARGET : controller.getState().route;
        controller.canvasClicked(target, action.componentId, elementKeyAt(action.element, event.target, point, window));
        controller.annotate(target, action.componentId, rectOf(action.element, scroll));
      }
    };
    // Plan 5 (review I2): an image whose file loads after it was described is described again.
    const onLoad = (event: Event) => {
      const tag = (event.target as Element | null)?.tagName;
      if (tag === "IMG" || tag === "VIDEO") controller.imageLoaded();
    };
    document.addEventListener("load", onLoad, true);
    document.addEventListener("loadeddata", onLoad, true);
    // Keys a rich text editor handles itself (keys.ts `shield`): stopped on the body on their way up,
    // after the editor and before Puck's listener on `document`.
    const shielded = new WeakSet<Event>();
    const onKeyDown = (event: KeyboardEvent) => {
      // Puck's own history and preview toggle never run: undo is the server's stack (ruling). See
      // keys.ts for why this listener, on window in the capture phase, runs before Puck's.
      const action = frameKeyAction(event);
      if (action.preventDefault) event.preventDefault();
      if (action.stop) event.stopImmediatePropagation();
      if (action.shield) shielded.add(event);
      if (action.send) controller.shortcut(action.send);
    };
    const onKeyDownBubbling = (event: KeyboardEvent) => {
      if (shielded.has(event)) event.stopPropagation();
    };
    const onFocusOut = () => controller.leftText();
    // Any typing on the canvas (a cloned text slot, a Puck inline field) is unsent work until it
    // reaches the page and the app: the app asks before a reload throws it away.
    const onInput = () => controller.noteTyping();
    const onDoubleClick = (event: MouseEvent) => {
      const state = controller.getState();
      if (state.mode !== "edit" || !state.site) return;
      const image = (event.target as Element | null)?.closest?.("img");
      const component = image?.closest("[data-puck-component]");
      const componentId = component?.getAttribute("data-puck-component");
      if (!image || !componentId) return;
      const target = isShellId(componentId) ? SHELL_TARGET : state.route;
      const props = componentProps(state.site, target, componentId);
      const src = image.getAttribute("src") ?? "";
      // The field whose value IS this picture; a picture no field holds (a clone's own art) asks nothing.
      const prop = props ? Object.keys(props).find((key) => props[key] === src && src.startsWith("/asset-store/")) : undefined;
      if (prop) controller.requestAsset(target, componentId, prop);
    };
    // Founder 2026-10-19: in edit mode the element a click would select is outlined (dashed) under the
    // pointer, found exactly as the click finds it. Worked out once per frame, and only when the pointer
    // is over another node or has moved within a section's blank space.
    let hovered: Element | null = null;
    let pending: PointerEvent | null = null;
    let hoverFrame = 0;
    const setHovered = (element: Element | null, scope?: Element) => {
      if (element === hovered) return;
      hovered?.removeAttribute(ELEMENT_HOVERED);
      hovered = element;
      if (hovered) markOutline(hovered, ELEMENT_HOVERED, scope ?? null);
    };
    const updateHover = () => {
      hoverFrame = 0;
      const event = pending;
      pending = null;
      if (!event) return;
      if (controller.getState().mode !== "edit") return setHovered(null);
      const { action } = clickIntent(event.target, "edit");
      if (action.kind !== "component" || !action.element) return setHovered(null);
      const key = elementKeyAt(action.element, event.target, { x: event.clientX, y: event.clientY }, window);
      if (key) return setHovered(findKeyedElement(action.element, key), action.element);
      // Blank space: the section, or its background once the section is selected (founder 2026-10-19).
      const target = isShellId(action.componentId) ? SHELL_TARGET : controller.getState().route;
      const background = controller.blankClickSelects(target, action.componentId);
      setHovered(background ? findKeyedElement(action.element, background) : action.element, action.element);
    };
    const onPointerMove = (event: PointerEvent) => {
      pending = event;
      if (!hoverFrame) hoverFrame = requestAnimationFrame(updateHover);
    };
    const onPointerLeave = () => {
      pending = null;
      setHovered(null);
    };
    document.addEventListener("pointermove", onPointerMove, true);
    document.documentElement.addEventListener("pointerleave", onPointerLeave);
    document.addEventListener("click", onClick, true);
    window.addEventListener("keydown", onKeyDown, true);
    document.body.addEventListener("keydown", onKeyDownBubbling);
    document.addEventListener("focusout", onFocusOut, true);
    document.addEventListener("input", onInput, true);
    document.addEventListener("dblclick", onDoubleClick, true);
    return () => {
      document.removeEventListener("click", onClick, true);
      document.removeEventListener("pointermove", onPointerMove, true);
      document.documentElement.removeEventListener("pointerleave", onPointerLeave);
      if (hoverFrame) cancelAnimationFrame(hoverFrame);
      setHovered(null);
      window.removeEventListener("keydown", onKeyDown, true);
      document.body.removeEventListener("keydown", onKeyDownBubbling);
      document.removeEventListener("focusout", onFocusOut, true);
      document.removeEventListener("input", onInput, true);
      document.removeEventListener("dblclick", onDoubleClick, true);
      document.removeEventListener("load", onLoad, true);
      document.removeEventListener("loadeddata", onLoad, true);
    };
  }, [controller]);

  // The selected text element's outline: an attribute, re-applied after every redraw of the page
  // (Puck draws an outside copy a frame later, and may replace the element). A frame later the
  // selection is also described again: Puck reports a click's selection mid-redraw.
  useEffect(() => {
    const settle = () => {
      controller.refreshSelection();
      apply();
      highlightKeptWords(controller);
    };
    const apply = () => {
      for (const element of document.querySelectorAll(`[${ELEMENT_SELECTED}]`)) element.removeAttribute(ELEMENT_SELECTED);
      const selection = state.selection;
      if (!selection) return;
      const scope = selectionScope(selection.target, selection.componentId);
      if (!scope) return;
      // The whole section is outlined like an element (founder 2026-10-19).
      const element = selection.elementKey ? findKeyedElement(scope, selection.elementKey) : scope;
      if (element) markOutline(element, ELEMENT_SELECTED, scope);
    };
    apply();
    const frame = requestAnimationFrame(settle);
    // Once more when a slower redraw has landed: the panel then shows the look a new copy of the site
    // (an undo) drew, not the one before it (the controller posts only when the look changed).
    const later = setTimeout(() => controller.refreshSelection(), 250);
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(later);
    };
  }, [controller, state.selection, state.mountKey, state.site]);

  // The header's menu lists the site's pages (plan 6): the config changes only when the pages do.
  const routesJson = state.site ? canonicalJson(Object.keys(state.site.pages).sort()) : "[]";
  const menu = useMemo(
    () => siteMenuPages(Object.fromEntries((JSON.parse(routesJson) as string[]).map((route) => [route, {}]))),
    [routesJson],
  );
  const config = useMemo(
    () => (state.brand ? buildPageConfig(state.brand, state.sections, menu) : null),
    [state.brand, menu, state.sections],
  );

  // Built once per change of the values it reads, never on a selection: re-rendering <Puck>
  // re-renders every section, and React 19 re-sets a clone's dangerouslySetInnerHTML on every render
  // of it, which rebuilds its DOM — the page above the selection reflows (stale annotate geometry)
  // and the text slots CloneEditor made editable in place stop being editable.
  const ready = state.status === "ready";
  const brand = ready ? state.brand : null;
  // The page with the header first and the footer last (plan 6, ruling R2).
  const site = ready ? state.site : null;
  const page = useMemo(() => (site ? editorPage(site, state.route) : null), [site, state.route]);
  const route = state.route;
  const mode = state.mode;
  const mountKey = state.mountKey;
  const editor = useMemo(() => {
    if (!brand || !config || !page) return null;
    return (
      <Puck
        config={config}
        data={page as unknown as Data}
        iframe={{ enabled: false }}
        key={mountKey}
        onChange={(data) => controller.pageEdited(route, data as unknown as NonNullable<typeof page>)}
        permissions={PERMISSIONS}
        ui={{
          previewMode: mode === "edit" ? "edit" : "interactive",
          viewports: { controlsVisible: false, current: { height: "auto", width: "100%" }, options: VIEWPORTS },
        }}
        viewports={VIEWPORTS}
      >
        <PuckBridge brand={brand} config={config} controller={controller} />
        <Puck.Preview />
      </Puck>
    );
  }, [brand, config, controller, mode, mountKey, page, route]);
  return editor;
}

function PuckBridge({ brand, config, controller }: { brand: BrandData; config: Config; controller: FrameController }) {
  const getPuck = useGetPuck();
  const selectedId = usePuck((store) => (store.selectedItem ? String(store.selectedItem.props.id) : null));

  useEffect(() => {
    controller.attachPuck({
      select(componentId, options) {
        const puck = getPuck();
        const itemSelector = componentId ? (puck.getSelectorForId(componentId) ?? null) : null;
        puck.dispatch({ type: "setUi", ui: { itemSelector } });
        if (componentId && options?.scroll !== false) {
          document.querySelector(`[data-puck-component="${CSS.escape(componentId)}"]`)?.scrollIntoView({ block: "nearest" });
        }
      },
      setMode(mode) {
        getPuck().dispatch({
          type: "setUi",
          ui: mode === "edit" ? { previewMode: "edit" } : { itemSelector: null, previewMode: "interactive" },
        });
      },
      showPage(page, selectedId) {
        getPuck().dispatch({ data: page as unknown as Data, recordHistory: false, type: "setData" });
        const puck = getPuck();
        // Puck's own history must never hold a snapshot from before an outside change: one entry,
        // the page as now shown (review finding S2a-1's backstop; its keys never reach Puck).
        puck.history.setHistories([{ id: `outside-${Date.now()}`, state: puck.appState }]);
        // Point Puck at the selected section by id, never by position (S2a-4), and re-describe it.
        const itemSelector = selectedId ? (puck.getSelectorForId(selectedId) ?? null) : null;
        puck.dispatch({ type: "setUi", ui: { itemSelector } });
        const item = selectedId && itemSelector ? puck.getItemById(selectedId) : null;
        if (item && selectedId) {
          const props = item.props as Record<string, unknown>;
          controller.reselected(selectedId, item.type, fieldsForComponent(config, brand, item.type, props), props);
        }
      },
    });
    return () => controller.attachPuck(null);
  }, [brand, config, controller, getPuck]);

  useEffect(() => {
    if (!selectedId) {
      controller.componentDeselected();
      return;
    }
    const item = getPuck().getItemById(selectedId);
    if (!item) return;
    const props = item.props as Record<string, unknown>;
    controller.componentSelected(selectedId, item.type, fieldsForComponent(config, brand, item.type, props), props);
  }, [brand, config, controller, getPuck, selectedId]);

  return null;
}
