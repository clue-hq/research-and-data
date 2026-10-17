import { useEffect, useMemo, useSyncExternalStore } from "react";
import { Puck, createUsePuck, useGetPuck, type Config, type Data, type Permissions, type Viewports } from "@puckeditor/core";
import type { BrandData } from "@clue/site-kit";
import { acceptAppMessage, frameToApp } from "@clue/site-kit/editor-protocol";
import { canonicalJson, pageFor } from "@clue/site-kit/editor-site";
import { SHELL_TARGET, type SitePage, type SiteShell } from "@clue/site-kit/site-document";
import type { BootContext } from "./boot";
import { buildPageConfig, shellFieldDescriptions } from "./config";
import { clickIntent, cssColorToHex, elementKeyAt, elementSelection, elementSummary, findKeyedElement, keyedElementsIn, rectOf } from "./dom";
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
  // from the page as drawn now.
  useEffect(() => {
    controller.attachDescriber((target, componentId, key) => {
      const scope = selectionScope(target, componentId);
      if (!scope) return { element: null, elements: [] };
      const found = key ? findKeyedElement(scope, key) : null;
      return {
        element: found ? elementSelection(found, window, toHex) : null,
        elements: keyedElementsIn(scope).map(elementSummary),
      };
    });
    return () => controller.attachDescriber(null);
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
        controller.elementClicked(SHELL_TARGET, action.part, elementKeyAt(action.element, event.target, point));
        controller.shellSelected(action.part);
        controller.annotate(SHELL_TARGET, action.part, rectOf(action.element, scroll));
      }
      if (action.kind === "component" && action.componentId) {
        controller.elementClicked(controller.getState().route, action.componentId, elementKeyAt(action.element, event.target, point));
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
