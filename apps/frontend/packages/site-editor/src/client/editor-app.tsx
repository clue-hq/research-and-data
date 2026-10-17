import { useEffect, useMemo, useSyncExternalStore } from "react";
import { Puck, createUsePuck, useGetPuck, type Config, type Data, type Permissions, type Viewports } from "@puckeditor/core";
import { RICH_PROPS, cloneButtonAt, cloneLinkAt, ownLinkSource, richSourceOf, type BrandData } from "@clue/site-kit";
import { richFromDom } from "@clue/site-kit/editor";
import { normalizeRich } from "@clue/site-kit/rich";
import type { ElementSelection, LabelSource, LinkSource, RichSource } from "@clue/site-kit/editor-protocol";
import { acceptAppMessage, frameToApp } from "@clue/site-kit/editor-protocol";
import { canonicalJson, pageFor } from "@clue/site-kit/editor-site";
import { SHELL_TARGET, type SitePage, type SiteShell } from "@clue/site-kit/site-document";
import type { BootContext } from "./boot";
import { buildPageConfig, shellFieldDescriptions } from "./config";
import {
  buttonAround,
  buttonLabelOf,
  clickIntent,
  computedBox,
  computedTypography,
  cssColorToHex,
  elementKeyAt,
  elementSelection,
  elementSummary,
  findKeyedElement,
  inspectableElementsIn,
  isButtonElement,
  rangeAt,
  rectOf,
  selectionOffsets,
  textElementAround,
  wordCount,
} from "./dom";
import { fieldsForComponent } from "./fields";
import { FrameController } from "./frame-controller";
import { frameKeyAction } from "./keys";
import { browserSectionDeps, loadSections } from "./sections";

const usePuck = createUsePuck();
// Insert, delete, duplicate and drag wait for the founder's designs (C13); in-place editing stays on.
const PERMISSIONS: Partial<Permissions> = { delete: false, drag: false, duplicate: false, edit: true, insert: false };
const VIEWPORTS: Viewports = [{ height: "auto", label: "Page", width: "100%" }];
const SHELL_SELECTED = "data-site-shell-selected";
const ELEMENT_SELECTED = "data-clue-el-selected";

/** Where a selection's elements live on the canvas: the header/footer, or a page section. */
function selectionScope(target: string, componentId: string): Element | null {
  if (target === SHELL_TARGET) {
    return componentId === "header" || componentId === "footer" ? document.querySelector(`.brand-root > ${componentId}`) : null;
  }
  return document.querySelector(`[data-puck-component="${CSS.escape(componentId)}"]`);
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

/** Which section or shell part an element on the canvas belongs to. */
function placeOf(element: Element): { target: string; componentId: string } | null {
  const shell = element.closest(".brand-root > header, .brand-root > footer");
  if (shell) return { componentId: shell.tagName.toLowerCase(), target: SHELL_TARGET };
  const component = element.closest("[data-puck-component]")?.getAttribute("data-puck-component");
  return component ? { componentId: component, target: "page" } : null;
}

const AGENT_LINK = "The agent's section sets this link; ask the agent to change it.";

/** The chosen element as the `selected` message carries it (plan 1's look, plus plan 2's facts). */
function describeElement(controller: FrameController, target: string, componentId: string, element: Element): ElementSelection {
  const described = elementSelection(element, window, toHex);
  const state = controller.getState();
  const key = described.key;
  let rich: RichSource | null = null;
  let link: LinkSource | null = null;
  const anchored = element.tagName === "A" || element.closest("a") !== null;
  if (target === SHELL_TARGET) {
    link = ownLinkSource(componentId === "header" ? "SiteHeader" : "SiteFooter", key);
  } else if (state.site && state.brand) {
    const item = pageFor(state.site, target)?.content.find((entry) => entry.props.id === componentId);
    if (item) {
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
        const agent = !(item.type in RICH_PROPS);
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
  if (target === SHELL_TARGET) {
    if (componentId === "header" && key === "cta") {
      rich = { prop: "ctaLabel" };
      labelSource = { kind: "prop", prop: "ctaLabel" };
      link = ownLinkSource("SiteHeader", key);
    }
  } else if (state.site && state.brand) {
    const item = pageFor(state.site, target)?.content.find((entry) => entry.props.id === componentId);
    const props = (item?.props ?? {}) as Record<string, unknown>;
    if (item?.type === "ClonedSection") {
      const clone = state.brand.clones[String(props.fragmentId ?? "")];
      const found = clone ? cloneButtonAt(clone, key) : null;
      if (found?.labelSlot) {
        const stored = (props.slots as Record<string, unknown> | undefined)?.[found.labelSlot];
        rich = typeof stored === "string" ? { prop: `slots.${found.labelSlot}` } : { fallback: normalizeRich(richFromDom(label), { links: false }), prop: `slots.${found.labelSlot}` };
        labelSource = { kind: "slot", slot: found.labelSlot };
      } else {
        labelSource = found?.labelText ? { find: found.labelText, kind: "replacement" } : { kind: "fixed", reason: CLONE_BUTTON_WORDS };
      }
      if (found?.hrefSlot) link = { kind: "slot", slot: found.hrefSlot };
      else if (found?.href) link = { find: found.href, kind: "replacement", shared: found.shared };
    } else if (item && item.type in RICH_PROPS) {
      if (key === "button") {
        rich = { prop: "buttonLabel" };
        labelSource = { kind: "prop", prop: "buttonLabel" };
      }
      link = ownLinkSource(item.type, key);
    } else if (item) {
      labelSource = { kind: "fixed", reason: AGENT_BUTTON };
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
      const found = key ? findKeyedElement(scope, key) : null;
      return {
        element: found ? (isButtonElement(found, window) ? describeButton(controller, target, componentId, found) : describeElement(controller, target, componentId, found)) : null,
        elements: inspectableElementsIn(scope, window).map(({ element, kind }) => elementSummary(element, kind)),
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
      if (action.kind === "shell") {
        event.stopPropagation();
        controller.elementClicked(SHELL_TARGET, action.part, elementKeyAt(action.element, event.target, point, window));
        controller.shellSelected(action.part);
        controller.annotate(SHELL_TARGET, action.part, rectOf(action.element, scroll));
      }
      if (action.kind === "component" && action.componentId) {
        controller.elementClicked(controller.getState().route, action.componentId, elementKeyAt(action.element, event.target, point, window));
        controller.annotate(controller.getState().route, action.componentId, rectOf(action.element, scroll));
      }
    };
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
      const props = state.site.pages[state.route]?.content.find((entry) => entry.props.id === componentId)?.props;
      const src = image.getAttribute("src") ?? "";
      // The field whose value IS this picture; a picture no field holds (a clone's own art) asks nothing.
      const prop = props ? Object.keys(props).find((key) => props[key] === src && src.startsWith("/asset-store/")) : undefined;
      if (prop) controller.requestAsset(state.route, componentId, prop);
    };
    document.addEventListener("click", onClick, true);
    window.addEventListener("keydown", onKeyDown, true);
    document.body.addEventListener("keydown", onKeyDownBubbling);
    document.addEventListener("focusout", onFocusOut, true);
    document.addEventListener("input", onInput, true);
    document.addEventListener("dblclick", onDoubleClick, true);
    return () => {
      document.removeEventListener("click", onClick, true);
      window.removeEventListener("keydown", onKeyDown, true);
      document.body.removeEventListener("keydown", onKeyDownBubbling);
      document.removeEventListener("focusout", onFocusOut, true);
      document.removeEventListener("input", onInput, true);
      document.removeEventListener("dblclick", onDoubleClick, true);
    };
  }, [controller]);

  // The shell is drawn by the page root, not by a Puck component, so its outline is ours (DR5).
  useEffect(() => {
    for (const element of document.querySelectorAll(`[${SHELL_SELECTED}]`)) element.removeAttribute(SHELL_SELECTED);
    const selection = state.selection;
    if (selection?.target === SHELL_TARGET) {
      document.querySelector(`.brand-root > ${selection.componentId}`)?.setAttribute(SHELL_SELECTED, "true");
    }
  }, [state.selection, state.mountKey]);

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
      if (!selection?.elementKey) return;
      const scope = selectionScope(selection.target, selection.componentId);
      const element = scope ? findKeyedElement(scope, selection.elementKey) : null;
      element?.setAttribute(ELEMENT_SELECTED, "true");
    };
    apply();
    const frame = requestAnimationFrame(settle);
    return () => cancelAnimationFrame(frame);
  }, [controller, state.selection, state.mountKey, state.site]);

  const shellJson = state.site?.shell ? canonicalJson(state.site.shell) : "";
  const shell = useMemo<SiteShell | null>(() => (shellJson ? (JSON.parse(shellJson) as SiteShell) : null), [shellJson]);
  const config = useMemo(
    () => (state.brand ? buildPageConfig(state.brand, shell, state.sections) : null),
    [state.brand, shell, state.sections],
  );
  useEffect(() => {
    controller.setShellFields(state.brand ? shellFieldDescriptions(state.brand) : null);
  }, [controller, state.brand]);

  // Built once per change of the values it reads, never on a selection: re-rendering <Puck>
  // re-renders every section, and React 19 re-sets a clone's dangerouslySetInnerHTML on every render
  // of it, which rebuilds its DOM — the page above the selection reflows (stale annotate geometry)
  // and the text slots CloneEditor made editable in place stop being editable.
  const ready = state.status === "ready";
  const brand = ready ? state.brand : null;
  const page = ready && state.site ? pageFor(state.site, state.route) : null;
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
        onChange={(data) => controller.pageEdited(route, data as unknown as SitePage)}
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
