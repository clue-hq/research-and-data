"""Bridge for the website-mode editor iframe.

The renderer's editor mode injects this script into the srcdoc document. It
does the following and nothing else: hover/selection outlines over
`data-node-id` elements, click-to-select posted to the parent shell,
suppression of link navigation AND invoker-command buttons inside the canvas,
(v7) double-click rich-text editing on Text nodes — a lazy editor-only Lexical
session posts one canonical `{type:"rich-text-commit", nodeId, content}` and the
SERVER validates that RichTextDocument before persistence — and two
parent-driven inbound actions: component preview
(`{type:"component-preview", nodeId, action:"open"|"close"}` opens/closes a
`<dialog>` node) and programmatic selection (`{type:"select-node", nodeId}`
selects a node as if the user had clicked it, echoing the normal `select`
message back). Security posture:

- The iframe runs with `sandbox="allow-scripts"` (NO allow-same-origin), so
  its origin is the literal string "null"; it cannot read the parent, only
  postMessage to it.
- Every message carries a per-render NONCE minted by the shell and passed
  through the render request; the shell validates source window + origin
  "null" + nonce before trusting a message, and the bridge ignores inbound
  messages without the nonce.
- The nonce is interpolated server-side; `render_bridge_script` rejects any
  nonce outside a strict charset so the substitution cannot become script
  injection.

v4 adds a generic read-only node-inspection protocol. Selection payloads and
`node-info` updates include parent/child identity, viewport + document geometry,
and an allowlisted computed-style snapshot. The parent may request any rendered
node with `{type:"inspect-node", nodeId}`; ResizeObserver/scroll/resize refresh
the selected node. These values inform the GUI only — mutations still go
through canonical WebOperations.

v5 replaces the section-only drag bridge with a generic direct-manipulation
contract for sections, containers, text, buttons, images, and custom-component
leaves. The server injects
the canonical movable/drop-parent id sets for the rendered page. A selected node
gets a drag handle; the bridge shows a ghost plus an axis-aware insertion marker
and posts `{type:"move-node", nodeId, newParentNodeId, index}`. The index is
measured after source removal, so one intent covers both reorder and reparent.

v6 adds class-backed resizing for containers, text, buttons, images, and
custom-component leaves. A selected resizable node gets right, bottom, and
corner handles. Inline width / height are used only as a transient live
preview; mouseup restores them and posts
`{type:"resize-node", nodeId, widthPx, heightPx}` so the parent can persist
canonical `w-[Npx]` / `h-[Npx]` classes through the normal versioned op path.

v7 replaces native contenteditable serialization with an editor-only Lexical
session loaded lazily inside the existing sandbox. The session exports the
library-independent RichTextDocument, reports selection formatting, and accepts
nonce-scoped format commands from the inspector. A whole session commits as one
SetRichText operation; Escape restores the exact pre-session HTML.

v8 reports the active DOM range rectangle plus mark/class/link state for a
parent-rendered floating toolbar. Its nonce-scoped command envelope covers theme
class facets, safe links, typed variables, and clear-formatting. A toolbar-focus
handshake keeps the iframe selection alive while parent controls own focus.

v9 cache-keys the editor-only runtime at the structured-block protocol version.
The bridge and runtime are deployed together, but the sandbox loads the runtime
as a public asset; changing the query key prevents a previously cached inline-
only bundle from flattening paragraphs and lists after an editor upgrade.

v10 relays P6.3 nested custom-component runtime state. A nested opaque-origin
frame is trusted only for its own renderer-created iframe element: source
window, runtime contract, nonce, canonical node id, and artifact pin must all
match the outer DOM. The outer frame then relays a nonce-scoped status through
the existing parent bridge; a component never addresses the React shell
directly.

v11 (slice 2, rulings R-A1/R-A4/R-A5) makes EVERY element hoverable, not only the
ones carrying a `data-node-id`. Inside a cloned band nothing carries one — the
markup is the harvested artifact's own — and those are exactly the elements a
marketer points at. Hover draws a box plus a name chip; the chip's words come
from `__LUMEN_NODE_NAMES__`, the display name of every node on the page baked in
at render in the same order the layers panel and the agent's TURN TARGET line
use, so the chip and the panel never disagree. A click still SELECTS the owning
node (everything downstream is node-shaped) and additionally posts
`{type:"annotate", address:{nodeId, path?, slot?, tag}, name, geometry, textLike}`
— a structural address, because an element with no id can only be named by its
position under the clone root the engine marks with `data-fragment-root`. The
shell posts `{type:"annotations", items:[{address, n}]}` back to draw numbered
badges, and `items: []` to clear.
"""

import json
import re
from typing import Any

NONCE_PATTERN = re.compile(r"^[A-Za-z0-9-]{8,64}$")

BRIDGE_CHANNEL = "lumen-web-bridge"

_BRIDGE_V0_TEMPLATE = """
(function () {
  var NONCE = "__LUMEN_BRIDGE_NONCE__";
  var CHANNEL = "lumen-web-bridge";
  var MOVABLE_NODE_IDS = new Set(__LUMEN_MOVABLE_NODE_IDS__);
  var DROP_PARENT_NODE_IDS = new Set(__LUMEN_DROP_PARENT_NODE_IDS__);
  var RESIZABLE_NODE_IDS = new Set(__LUMEN_RESIZABLE_NODE_IDS__);
  var ROOT_NODE_ID = __LUMEN_ROOT_NODE_ID__;
  // F5: the WHOLE document's `{route: page_id}` map — every page, not just the
  // rendered one, because the point of a site-internal link is to leave this
  // page. Consulted only to translate an already-prevented anchor click.
  var PAGE_ROUTES = __LUMEN_PAGE_ROUTES__;
  // R-A4/R-A5: the display name of every node on THIS page, in the same order the
  // layers panel and the agent's TURN TARGET line use. Baked in so the hover chip can
  // name a band without a round trip to the shell.
  var NODE_NAMES = __LUMEN_NODE_NAMES__;
  var selected = null;
  var hoverEl = null;
  var hoverBox = null;
  var hoverLabel = null;
  var badgeLayer = null;
  var lastAnnotations = null;
  var TEXT_LIKE =
    /^(h[1-6]|p|span|a|button|li|blockquote|figcaption|label|strong|em|small|td|th|dt|dd)$/;

  var editing = null;
  var editingOriginal = "";
  var editingOriginalDocument = "";
  var editingSession = null;
  var editingRoot = null;
  var editingGeneration = 0;
  var editingBlurTimer = null;
  var editingToolbarActive = false;
  var richTextRuntimePromise = null;
  var metricsFrame = null;
  var resizeObserver = null;

  var style = document.createElement("style");
  style.textContent =
    // v11: `lumen-hover` is VESTIGIAL — the node-level dashed outline was replaced by
    // the element-level hover box + name chip below, so nothing adds the class any
    // more. The rule and the several `classList.remove` calls are kept so a stale
    // class surviving on a node (e.g. inside a drag clone) still cannot paint.
    "[data-node-id].lumen-hover{outline:1.5px dashed rgba(79,111,255,0.7);outline-offset:2px;}" +
    "[data-node-id].lumen-selected{outline:2px solid rgba(79,111,255,0.95);outline-offset:2px;}" +
    "[data-node-id].lumen-editing{outline:2px solid rgba(34,197,146,0.95);outline-offset:2px;cursor:text;}" +
    ".lumen-rich-editor-root.is-inline{display:inline;}" +
    ".lumen-rich-editor-root.is-inline>p{display:contents;}" +
    ".lumen-rich-editor-root.is-structured{display:block;}" +
    ".lumen-rich-editor-root.is-structured>p," +
    ".lumen-rich-editor-root.is-structured>ul," +
    ".lumen-rich-editor-root.is-structured>ol{margin:0;}" +
    ".lumen-rich-editor-root.is-structured>*+*{margin-top:.75em;}" +
    ".lumen-rich-editor-root.is-structured>ul," +
    ".lumen-rich-editor-root.is-structured>ol{padding-inline-start:1.5em;}" +
    ".lumen-rich-editor-root.is-structured ul{list-style-type:disc;}" +
    ".lumen-rich-editor-root.is-structured ol{list-style-type:decimal;}" +
    ".lumen-rich-editor-root.is-structured li:has(>ul:only-child,>ol:only-child){list-style-type:none;}" +
    ".lumen-rich-editor-root.is-structured li+li{margin-top:.25em;}" +
    ".lumen-hover-box{position:absolute;pointer-events:none;" +
    "border:1.5px solid rgba(79,111,255,0.85);border-radius:2px;z-index:2147483000;}" +
    ".lumen-hover-label{position:absolute;pointer-events:none;background:#4f6fff;" +
    "color:#fff;font:11px/16px ui-monospace,Menlo,monospace;padding:1px 6px;" +
    "border-radius:3px;z-index:2147483001;white-space:nowrap;}" +
    ".lumen-annotation-outline{position:absolute;pointer-events:none;" +
    "border:1.5px dashed rgba(234,179,8,0.95);z-index:2147482999;}" +
    ".lumen-annotation-badge{position:absolute;pointer-events:none;min-width:18px;" +
    "height:18px;border-radius:9px;background:#f0a;color:#fff;" +
    "font:600 11px/18px system-ui,sans-serif;text-align:center;padding:0 5px;" +
    "z-index:2147483002;}";
  document.head.appendChild(style);

  function rounded(value) {
    return Math.round(Number(value || 0) * 100) / 100;
  }

  function rectInfo(rect, offsetX, offsetY) {
    return {
      x: rounded(rect.left + offsetX),
      y: rounded(rect.top + offsetY),
      top: rounded(rect.top + offsetY),
      right: rounded(rect.right + offsetX),
      bottom: rounded(rect.bottom + offsetY),
      left: rounded(rect.left + offsetX),
      width: rounded(rect.width),
      height: rounded(rect.height)
    };
  }

  function authoredClasses(el) {
    return Array.prototype.slice
      .call(el.classList || [])
      .filter(function (name) { return name.indexOf("lumen-") !== 0; })
      .join(" ");
  }

  function directNodeElements(el) {
    return Array.prototype.slice
      .call(el.querySelectorAll("[data-node-id]"))
      .filter(function (candidate) {
        if (el === document.body) {
          return candidate.parentElement === document.body;
        }
        return candidate.parentElement &&
          candidate.parentElement.closest("[data-node-id]") === el;
      });
  }

  function directNodeChildren(el) {
    return directNodeElements(el)
      .map(function (candidate) {
        return candidate.getAttribute("data-node-id");
      })
      .filter(Boolean);
  }

  function nodeInfo(el) {
    if (!el) return null;
    var rect = el.getBoundingClientRect();
    var computed = window.getComputedStyle(el);
    var parentNode = el.parentElement
      ? el.parentElement.closest("[data-node-id]")
      : null;
    return {
      nodeId: el.getAttribute("data-node-id"),
      tag: el.tagName.toLowerCase(),
      tv: el.hasAttribute("data-tv"),
      btn: el.hasAttribute("data-btn"),
      text: (el.textContent || "").trim().slice(0, 60),
      parentNodeId: parentNode ? parentNode.getAttribute("data-node-id") : null,
      childNodeIds: directNodeChildren(el),
      geometry: {
        viewport: rectInfo(rect, 0, 0),
        document: rectInfo(rect, window.scrollX, window.scrollY)
      },
      computedStyle: {
        authoredClasses: authoredClasses(el),
        display: computed.display,
        position: computed.position,
        boxSizing: computed.boxSizing,
        width: computed.width,
        height: computed.height,
        minWidth: computed.minWidth,
        minHeight: computed.minHeight,
        maxWidth: computed.maxWidth,
        maxHeight: computed.maxHeight,
        marginTop: computed.marginTop,
        marginRight: computed.marginRight,
        marginBottom: computed.marginBottom,
        marginLeft: computed.marginLeft,
        paddingTop: computed.paddingTop,
        paddingRight: computed.paddingRight,
        paddingBottom: computed.paddingBottom,
        paddingLeft: computed.paddingLeft,
        gap: computed.gap,
        rowGap: computed.rowGap,
        columnGap: computed.columnGap,
        flexDirection: computed.flexDirection,
        flexWrap: computed.flexWrap,
        flexGrow: computed.flexGrow,
        flexShrink: computed.flexShrink,
        justifyContent: computed.justifyContent,
        alignItems: computed.alignItems,
        alignSelf: computed.alignSelf,
        gridTemplateColumns: computed.gridTemplateColumns,
        gridTemplateRows: computed.gridTemplateRows,
        fontFamily: computed.fontFamily,
        fontSize: computed.fontSize,
        fontWeight: computed.fontWeight,
        lineHeight: computed.lineHeight,
        textAlign: computed.textAlign,
        color: computed.color,
        backgroundColor: computed.backgroundColor,
        borderTopWidth: computed.borderTopWidth,
        borderRightWidth: computed.borderRightWidth,
        borderBottomWidth: computed.borderBottomWidth,
        borderLeftWidth: computed.borderLeftWidth,
        borderRadius: computed.borderRadius,
        objectFit: computed.objectFit,
        objectPosition: computed.objectPosition,
        overflowX: computed.overflowX,
        overflowY: computed.overflowY,
        opacity: computed.opacity
      }
    };
  }

  // --- Slice 2: element-level hover naming + `annotate` addresses -------------
  // Everything the bridge itself injects into the page. It is chrome, never content:
  // it is skipped when a structural path is measured and never annotated itself.
  function isBridgeEl(el) {
    return !!(el && el.closest && el.closest(".lumen-hover-box,.lumen-hover-label," +
      ".lumen-annotation-layer,.lumen-annotation-outline,.lumen-annotation-badge," +
      ".lumen-grip,.lumen-resize-handle,.lumen-resize-badge,.lumen-drop-marker," +
      ".lumen-drag-ghost"));
  }

  function ownerNode(el) {
    return el && el.closest ? el.closest("[data-node-id]") : null;
  }

  // Spec 3.1: structural path from the OWNING node's element to `el`, 1-based, element
  // children only, bridge-injected nodes excluded (they are never inside a node's
  // subtree). Inside a cloned band the markup is the artifact's own — it carries no
  // node ids — so position is the only address there is.
  function elementPath(el, owner) {
    if (!el || !owner || el === owner) return null;
    var parts = [], cur = el;
    while (cur && cur !== owner) {
      var parent = cur.parentElement;
      if (!parent) return null;
      var index = 0, sib = parent.firstElementChild, position = 0;
      while (sib) {
        if (!isBridgeEl(sib)) {
          index += 1;
          if (sib === cur) { position = index; break; }
        }
        sib = sib.nextElementSibling;
      }
      if (!position) return null;
      parts.unshift(":nth-child(" + position + ")");
      cur = parent;
    }
    return parts.join(" > ");
  }

  function addressOf(el) {
    var owner = ownerNode(el);
    if (!owner) return null;
    var ownerId = owner.getAttribute("data-node-id");
    // Spec 3.1: a structural path exists ONLY inside a clone. `data-fragment-root` —
    // which the engine stamps on every clone wrapper in editor mode — is the whole
    // truth here, and deliberately the ONLY test. An earlier draft also pathed any
    // id-less element under any owner, which caught a `<strong>` inside a vocabulary
    // text node's rich-text markup and a plain child of a section: those are not in a
    // clone, so the path would later be resolved against a fragment HTML that does not
    // exist. A vocabulary node's descendants therefore address as `{nodeId, tag}` with
    // no path, `labelFor` shows the owner's display name, and `resolveAddress` returns
    // the owner element.
    var isFragment = owner.hasAttribute("data-fragment-root");
    var path = isFragment ? elementPath(el, owner) : null;
    var slot = el.getAttribute ? el.getAttribute("data-lumen-slot") : null;
    return {
      nodeId: ownerId,
      path: path || undefined,
      slot: slot || undefined,
      tag: el.tagName.toLowerCase()
    };
  }

  function labelFor(el, address) {
    if (address.path) {
      return address.slot ? address.tag + " \\u00b7 " + address.slot : address.tag;
    }
    return NODE_NAMES[address.nodeId] || address.tag;
  }

  function placeBox(box, rect) {
    box.style.left = (rect.left + window.scrollX) + "px";
    box.style.top = (rect.top + window.scrollY) + "px";
    box.style.width = rect.width + "px";
    box.style.height = rect.height + "px";
  }

  function showHover(el) {
    if (!hoverBox) {
      hoverBox = document.createElement("div");
      hoverBox.className = "lumen-hover-box";
      document.body.appendChild(hoverBox);
      hoverLabel = document.createElement("div");
      hoverLabel.className = "lumen-hover-label";
      document.body.appendChild(hoverLabel);
    }
    var address = addressOf(el);
    if (!address) return hideHover();
    var rect = el.getBoundingClientRect();
    placeBox(hoverBox, rect);
    hoverLabel.textContent = labelFor(el, address);
    hoverLabel.style.left = (rect.left + window.scrollX) + "px";
    hoverLabel.style.top = Math.max(0, rect.top + window.scrollY - 18) + "px";
    hoverBox.style.display = hoverLabel.style.display = "block";
  }

  function hideHover() {
    if (hoverBox) {
      hoverBox.style.display = "none";
      hoverLabel.style.display = "none";
    }
  }

  // The inverse of `addressOf`: an address the shell hands back becomes the element it
  // was measured from. Same bridge-element exclusion, or a badge would drift the moment
  // a grip or a hover box existed when the path was taken but not when it is resolved.
  function resolveAddress(address) {
    if (!address || typeof address.nodeId !== "string") return null;
    var owner = document.querySelector(
      '[data-node-id="' + CSS.escape(address.nodeId) + '"]'
    );
    if (!owner || !address.path) return owner;
    var cur = owner, parts = address.path.split(" > ");
    for (var i = 0; i < parts.length; i++) {
      var m = /^:nth-child\\((\\d+)\\)$/.exec(parts[i]);
      if (!m) return null;
      var n = parseInt(m[1], 10), sib = cur.firstElementChild, count = 0, next = null;
      while (sib) {
        if (!isBridgeEl(sib)) {
          count += 1;
          if (count === n) { next = sib; break; }
        }
        sib = sib.nextElementSibling;
      }
      if (!next) return null;
      cur = next;
    }
    return cur;
  }

  function renderAnnotations(items) {
    if (!badgeLayer) {
      badgeLayer = document.createElement("div");
      badgeLayer.className = "lumen-annotation-layer";
      document.body.appendChild(badgeLayer);
    }
    badgeLayer.innerHTML = "";
    (items || []).forEach(function (item) {
      var el = resolveAddress(item && item.address);
      if (!el) return;
      var rect = el.getBoundingClientRect();
      var outline = document.createElement("div");
      outline.className = "lumen-annotation-outline";
      placeBox(outline, rect);
      badgeLayer.appendChild(outline);
      var badge = document.createElement("div");
      badge.className = "lumen-annotation-badge";
      badge.textContent = String(item.n);
      badge.style.left = (rect.right + window.scrollX - 9) + "px";
      badge.style.top = (rect.top + window.scrollY - 9) + "px";
      badgeLayer.appendChild(badge);
    });
  }

  function post(type, payload) {
    var message = { channel: CHANNEL, nonce: NONCE, type: type };
    if (payload) {
      for (var key in payload) message[key] = payload[key];
    }
    // srcdoc sandbox frames have a null origin, so "*" is the only valid
    // target; authenticity is carried by source-window + nonce parent-side.
    parent.postMessage(message, "*");
  }

  function postNodeInfo(el) {
    if (el && el.isConnected) post("node-info", { node: nodeInfo(el) });
  }

  function customComponentFrameFor(event, data) {
    if (
      data.channel !== "lumen-custom-component-runtime" ||
      data.contractVersion !== 1 ||
      typeof data.runtimeNonce !== "string" ||
      typeof data.nodeId !== "string" ||
      typeof data.artifactId !== "string"
    ) {
      return null;
    }
    var frames = document.querySelectorAll(
      "iframe[data-lumen-custom-component-runtime='true']"
    );
    for (var index = 0; index < frames.length; index += 1) {
      var frame = frames[index];
      if (
        frame.contentWindow === event.source &&
        frame.getAttribute("data-runtime-contract-version") === "1" &&
        frame.getAttribute("data-runtime-nonce") === data.runtimeNonce &&
        frame.getAttribute("data-node-id-ref") === data.nodeId &&
        frame.getAttribute("data-artifact-id") === data.artifactId
      ) {
        return frame;
      }
    }
    return null;
  }

  function relayCustomComponentRuntime(event, data) {
    var frame = customComponentFrameFor(event, data);
    if (!frame) return false;
    var host = frame.closest("[data-custom-component-node-id]");
    if (!host || host.closest("[aria-hidden='true']")) return true;
    if (data.type === "height") {
      var height = Number(data.height);
      if (!Number.isFinite(height) || height < 1 || height > 10000) return true;
      if (host.getAttribute("data-custom-component-intrinsic") === "true") {
        frame.style.height = Math.ceil(height) + "px";
        scheduleSelectedInfo();
      }
    }
    if (data.type === "ready") {
      host.setAttribute("data-custom-component-runtime-state", "ready");
    } else if (data.type === "error") {
      host.setAttribute("data-custom-component-runtime-state", "error");
      var state = host.querySelector(".lumen-custom-component-state");
      if (state) state.textContent = "Runtime error";
    } else if (
      data.type !== "height" &&
      data.type !== "recoverable-error"
    ) {
      return true;
    }
    post("custom-component-runtime", {
      nodeId: data.nodeId,
      artifactId: data.artifactId,
      state:
        data.type === "error"
          ? "error"
          : data.type === "ready"
            ? "ready"
            : data.type,
      height:
        data.type === "height" && Number.isFinite(Number(data.height))
          ? Math.ceil(Number(data.height))
          : null,
      message:
        typeof data.message === "string" ? data.message.slice(0, 500) : null
    });
    return true;
  }

  function scheduleSelectedInfo() {
    if (!selected || metricsFrame !== null) return;
    metricsFrame = window.requestAnimationFrame(function () {
      metricsFrame = null;
      positionSelectionControls(selected);
      postNodeInfo(selected);
    });
  }

  function observeSelected() {
    if (resizeObserver) resizeObserver.disconnect();
    if (selected && typeof ResizeObserver !== "undefined") {
      if (!resizeObserver) {
        resizeObserver = new ResizeObserver(scheduleSelectedInfo);
      }
      resizeObserver.observe(selected);
      if (selected.parentElement) resizeObserver.observe(selected.parentElement);
    }
  }

  function setSelected(el) {
    if (selected) selected.classList.remove("lumen-selected");
    selected = el;
    if (el) {
      el.classList.remove("lumen-hover");
      el.classList.add("lumen-selected");
    }
    post("select", { node: nodeInfo(el) });
    observeSelected();
    showGripFor(el);
    showResizeHandlesFor(el);
  }

  // R-A1: EVERY element is hoverable, not only the ones carrying a node id — inside a
  // cloned band nothing carries one, and those are exactly the elements a marketer
  // points at. The box + name chip replace the old node-only dashed outline.
  document.addEventListener("mouseover", function (event) {
    var el = event.target;
    if (!el || isBridgeEl(el) || el === document.body || el === document.documentElement) {
      return hideHover();
    }
    if (editing && editing.contains(el)) return hideHover();
    showHover(el);
    var owner = ownerNode(el);
    if (hoverEl && hoverEl !== owner) hoverEl.classList.remove("lumen-hover");
    hoverEl = owner;
  });

  document.addEventListener("mouseout", function (event) {
    if (!event.relatedTarget) hideHover();
  });

  // Capture phase: links in the canvas must never navigate the iframe, and
  // element clicks become selection.
  document.addEventListener(
    "click",
    function (event) {
      var anchor =
        event.target && event.target.closest ? event.target.closest("a") : null;
      if (anchor) {
        event.preventDefault();
        // F5: a link whose RAW href is one of this document's routes is a page
        // switch, reported to the shell (which owns the active page). The raw
        // attribute, never `.href` — the browser resolves that against the
        // srcdoc's null origin, so "/pricing" would arrive as an absolute URL.
        // `hasOwnProperty` so an href like "constructor" cannot name a
        // prototype member. Any other link stays merely prevented, as before.
        var href = anchor.getAttribute("href");
        if (
          typeof href === "string" &&
          Object.prototype.hasOwnProperty.call(PAGE_ROUTES, href)
        ) {
          post("lumen:navigate", { pageId: PAGE_ROUTES[href] });
        }
      }
      var cmdBtn =
        event.target && event.target.closest
          ? event.target.closest("button[commandfor]")
          : null;
      if (cmdBtn) event.preventDefault();
      if (
        event.target &&
        event.target.closest &&
        event.target.closest(".lumen-grip, .lumen-resize-handle, .lumen-resize-badge")
      ) {
        return;
      }
      // Clicks inside the element being edited belong to the caret. A click on
      // another canvas node explicitly settles the whole local edit first.
      if (editing && editing.contains(event.target)) return;
      if (editing) stopEditing(true);
      var el =
        event.target && event.target.closest
          ? event.target.closest("[data-node-id]")
          : null;
      setSelected(el);
      // R-A1: selection still lands on the OWNING node (everything downstream — the
      // inspector, the grips, the turn's scope — is node-shaped). The annotation is a
      // SECOND, finer report about the exact element under the cursor, which inside a
      // cloned band has no node id of its own.
      var target = event.target;
      if (target && !isBridgeEl(target) && target !== document.body) {
        var address = addressOf(target);
        if (address) {
          var r = target.getBoundingClientRect();
          post("annotate", {
            address: address,
            name: labelFor(target, address),
            textLike:
              TEXT_LIKE.test(address.tag) &&
              (target.textContent || "").trim().length > 0,
            geometry: {
              viewport: rectInfo(r, 0, 0),
              document: rectInfo(r, window.scrollX, window.scrollY)
            }
          });
        }
      }
    },
    true
  );

  function clearEditingBlurTimer() {
    if (editingBlurTimer !== null) {
      window.clearTimeout(editingBlurTimer);
      editingBlurTimer = null;
    }
  }

  function scheduleEditingBlurCommit() {
    if (!editing || editingToolbarActive) return;
    clearEditingBlurTimer();
    editingBlurTimer = window.setTimeout(function () {
      editingBlurTimer = null;
      if (editing) stopEditing(true);
    }, 180);
  }

  function loadRichTextRuntime() {
    if (window.LumenRichTextRuntime) {
      return Promise.resolve(window.LumenRichTextRuntime);
    }
    if (!richTextRuntimePromise) {
      richTextRuntimePromise = new Promise(function (resolve, reject) {
        var script = document.createElement("script");
        script.src = "/vendor/web-rich-text-runtime.js?v=structured-blocks-v2";
        script.async = true;
        script.onload = function () {
          if (window.LumenRichTextRuntime) resolve(window.LumenRichTextRuntime);
          else reject(new Error("rich-text runtime loaded without registering"));
        };
        script.onerror = function () {
          reject(new Error("rich-text runtime failed to load"));
        };
        document.head.appendChild(script);
      });
    }
    return richTextRuntimePromise;
  }

  // v7: a whole Lexical edit session remains local until one atomic commit.
  function stopEditing(commit) {
    if (!editing) return;
    clearEditingBlurTimer();
    var el = editing;
    var id = el.getAttribute("data-node-id");
    var session = editingSession;
    var documentValue = session ? session.getDocument() : null;
    var changed =
      Boolean(documentValue) &&
      JSON.stringify(documentValue) !== editingOriginalDocument;
    var settledHtml =
      commit && changed && session ? session.getHtml() : editingOriginal;
    if (session) session.destroy();
    editing = null;
    editingSession = null;
    editingRoot = null;
    editingToolbarActive = false;
    editingGeneration += 1;
    el.classList.remove("lumen-editing");
    el.innerHTML = settledHtml;
    if (commit && changed) {
      post("rich-text-commit", {
        nodeId: id,
        content: documentValue
      });
    }
    editingOriginal = "";
    editingOriginalDocument = "";
    post("edit-end", { nodeId: id, committed: Boolean(commit), changed: changed });
  }

  function beginEditing(el) {
    if (!el || editing === el) return;
    stopEditing(true);
    var generation = ++editingGeneration;
    editing = el;
    editingOriginal = el.innerHTML;
    editingOriginalDocument = "";
    editingSession = null;
    editingToolbarActive = false;
    var textVariant = el.getAttribute("data-tv") || "body";
    var structured = textVariant === "body" || textVariant === "small";
    editingRoot = document.createElement(structured ? "div" : "span");
    editingRoot.className =
      "lumen-rich-editor-root " + (structured ? "is-structured" : "is-inline");
    el.innerHTML = "";
    el.appendChild(editingRoot);
    el.classList.remove("lumen-hover");
    el.classList.add("lumen-editing");
    post("edit-start", { nodeId: el.getAttribute("data-node-id") });
    loadRichTextRuntime()
      .then(function (runtime) {
        if (generation !== editingGeneration || editing !== el || !editingRoot) return;
        editingSession = runtime.mount(editingRoot, {
          initialHtml: editingOriginal,
          textVariant: textVariant,
          onSelectionStateChange: function (selection) {
            if (editing === el) {
              post("rich-text-selection", {
                nodeId: el.getAttribute("data-node-id"),
                selection: selection
              });
            }
          },
          onCommitRequest: function () { stopEditing(true); },
          onCancelRequest: function () { stopEditing(false); }
        });
        editingOriginalDocument = JSON.stringify(editingSession.getDocument());
        editingSession.focus();
      })
      .catch(function (error) {
        if (generation !== editingGeneration || editing !== el) return;
        var id = el.getAttribute("data-node-id");
        editing = null;
        editingRoot = null;
        editingToolbarActive = false;
        editingGeneration += 1;
        el.classList.remove("lumen-editing");
        el.innerHTML = editingOriginal;
        editingOriginal = "";
        editingOriginalDocument = "";
        post("edit-error", {
          nodeId: id,
          message: String(error && error.message ? error.message : error)
        });
        post("edit-end", { nodeId: id, committed: false, changed: false });
      });
  }

  document.addEventListener(
    "dblclick",
    function (event) {
      var el =
        event.target && event.target.closest
          ? event.target.closest("[data-node-id][data-tv]")
          : null;
      beginEditing(el);
    },
    true
  );

  document.addEventListener(
    "focusout",
    function (event) {
      if (!editing || !editing.contains(event.target)) return;
      scheduleEditingBlurCommit();
    },
    true
  );

  document.addEventListener("keydown", function (event) {
    if (editing) {
      if (event.key === "Escape") {
        event.preventDefault();
        stopEditing(false);
      } else if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        stopEditing(true);
      }
      return;
    }
    if (event.key === "Escape" && selected && !dragState && !resizeState) {
      setSelected(null);
    }
  });

  window.addEventListener("message", function (event) {
    var data = event.data || {};
    if (relayCustomComponentRuntime(event, data)) return;
    if (event.source !== parent || data.channel !== CHANNEL || data.nonce !== NONCE) return;
    if (data.type === "rich-text-command") {
      if (
        editing &&
        editingSession &&
        data.command &&
        typeof data.command === "object" &&
        data.nodeId === editing.getAttribute("data-node-id")
      ) {
        clearEditingBlurTimer();
        editingSession.command(data.command);
        editingSession.setInteractionActive(false);
        editingToolbarActive = false;
        editingSession.focus();
      }
    }
    if (data.type === "rich-text-toolbar") {
      if (
        editing &&
        editingSession &&
        data.nodeId === editing.getAttribute("data-node-id")
      ) {
        editingToolbarActive = data.active === true;
        clearEditingBlurTimer();
        editingSession.setInteractionActive(editingToolbarActive);
        if (!editingToolbarActive) {
          editingSession.focus();
          editingSession.refreshSelection();
        }
      }
    }
    if (data.type === "rich-text-settle") {
      if (
        editing &&
        data.nodeId === editing.getAttribute("data-node-id") &&
        (data.action === "commit" || data.action === "cancel")
      ) {
        stopEditing(data.action === "commit");
      }
    }
    if (data.type === "clear") {
      if (editing) stopEditing(true);
      if (selected) {
        selected.classList.remove("lumen-selected");
        selected = null;
        observeSelected();
        removeGrip();
        removeResizeControls();
      }
    }
    if (data.type === "inspect-node") {
      var inspected = document.querySelector(
        '[data-node-id="' + CSS.escape(String(data.nodeId || "")) + '"]'
      );
      if (inspected) postNodeInfo(inspected);
    }
    if (data.type === "component-preview") {
      var el = document.querySelector(
        '[data-node-id="' + CSS.escape(String(data.nodeId || "")) + '"]'
      );
      if (el && el.tagName === "DIALOG") {
        if (data.action === "open" && !el.open) el.showModal();
        if (data.action === "close" && el.open) el.close();
      }
    }
    if (data.type === "annotations") {
      // The shell owns the numbering; the bridge only draws it. An empty list is the
      // clear, so a settled turn erases its badges through the same one message.
      lastAnnotations = Array.isArray(data.items) ? data.items : [];
      renderAnnotations(lastAnnotations);
      return;
    }
    if (data.type === "select-node") {
      var target = document.querySelector(
        '[data-node-id="' + CSS.escape(String(data.nodeId || "")) + '"]'
      );
      if (target) {
        if (editing && target !== editing) stopEditing(true);
        setSelected(target);
      }
    }
  });

  // v5: generic reorder + reparent. The iframe computes a destination parent
  // and an insertion index after source removal; the shell validates that
  // intent against the canonical WebDoc before persisting MoveNode.
  var grip = null;
  var dropMarker = null;
  var dropParentEl = null;
  var dragGhost = null;
  var dragState = null;
  var resizeHandles = [];
  var resizeBadge = null;
  var resizeState = null;

  var structureStyle = document.createElement("style");
  structureStyle.textContent =
    ".lumen-grip{position:absolute;z-index:2147483000;display:flex;align-items:center;" +
    "justify-content:center;width:28px;height:28px;border-radius:8px;cursor:grab;" +
    "background:rgba(79,111,255,0.97);color:#fff;font-size:15px;line-height:1;" +
    "user-select:none;box-shadow:0 4px 14px rgba(31,41,90,.28);}" +
    ".lumen-drag-ghost{position:fixed;z-index:2147482998;pointer-events:none;opacity:.62;" +
    "overflow:hidden;max-width:280px;max-height:180px;transform:rotate(.5deg);" +
    "box-shadow:0 12px 30px rgba(31,41,90,.24);border-radius:6px;}" +
    ".lumen-drop-marker{position:absolute;z-index:2147483001;pointer-events:none;" +
    "background:rgba(79,111,255,.98);border-radius:3px;}" +
    ".lumen-drop-marker::before{content:'';position:absolute;width:9px;height:9px;" +
    "border-radius:999px;background:rgba(79,111,255,.98);}" +
    ".lumen-drop-marker.is-block::before{left:-3px;top:-3px;}" +
    ".lumen-drop-marker.is-row::before{left:-3px;top:-3px;}" +
    ".lumen-drop-parent{box-shadow:inset 0 0 0 2px rgba(79,111,255,.55)!important;}" +
    ".lumen-resize-handle{position:absolute;z-index:2147483002;width:12px;height:12px;" +
    "padding:0;border:2px solid #fff;border-radius:999px;background:rgba(79,111,255,.98);" +
    "box-shadow:0 1px 5px rgba(31,41,90,.35);touch-action:none;}" +
    ".lumen-resize-handle[data-axis='width']{cursor:ew-resize;}" +
    ".lumen-resize-handle[data-axis='height']{cursor:ns-resize;}" +
    ".lumen-resize-handle[data-axis='both']{cursor:nwse-resize;}" +
    ".lumen-resize-badge{position:absolute;z-index:2147483003;pointer-events:none;" +
    "padding:4px 7px;border-radius:6px;background:#172033;color:#fff;font:11px/1.2 ui-monospace,monospace;" +
    "box-shadow:0 3px 10px rgba(31,41,90,.24);}";
  document.head.appendChild(structureStyle);

  function nodeId(el) {
    return el && el.getAttribute ? el.getAttribute("data-node-id") : null;
  }

  function parentNodeElement(el) {
    return el && el.parentElement
      ? el.parentElement.closest("[data-node-id]")
      : null;
  }

  function canDropInto(el) {
    var id = nodeId(el);
    return Boolean(
      id &&
      DROP_PARENT_NODE_IDS.has(id) &&
      dragState &&
      el !== dragState.sourceEl &&
      !dragState.sourceEl.contains(el)
    );
  }

  function flowAxis(el) {
    if (el === document.body) return "block";
    var computed = window.getComputedStyle(el);
    if (
      (computed.display === "flex" || computed.display === "inline-flex") &&
      (computed.flexDirection === "row" || computed.flexDirection === "row-reverse")
    ) {
      return "row";
    }
    if (
      (computed.display === "grid" || computed.display === "inline-grid") &&
      computed.gridTemplateColumns &&
      computed.gridTemplateColumns !== "none" &&
      computed.gridTemplateColumns.trim().split(/\\s+/).length > 1
    ) {
      return "row";
    }
    return "block";
  }

  function boundaryCandidate(parentEl, parentNodeId, clientX, clientY) {
    var axis = flowAxis(parentEl);
    var children = directNodeElements(parentEl).filter(function (child) {
      return nodeId(child) !== dragState.nodeId;
    });
    var coordinate = axis === "row" ? clientX : clientY;
    var index = children.length;
    for (var i = 0; i < children.length; i++) {
      var rect = children[i].getBoundingClientRect();
      var center =
        axis === "row"
          ? rect.left + rect.width / 2
          : rect.top + rect.height / 2;
      if (coordinate < center) {
        index = i;
        break;
      }
    }
    return {
      parentEl: parentEl,
      newParentNodeId: parentNodeId,
      index: index,
      axis: axis,
      children: children
    };
  }

  function nearFlowEdge(el, parentEl, clientX, clientY) {
    var axis = flowAxis(parentEl);
    var rect = el.getBoundingClientRect();
    var size = axis === "row" ? rect.width : rect.height;
    var coordinate = axis === "row" ? clientX : clientY;
    var start = axis === "row" ? rect.left : rect.top;
    var threshold = Math.min(32, Math.max(10, size * 0.2));
    return coordinate <= start + threshold || coordinate >= start + size - threshold;
  }

  function topLevelCandidate(clientY) {
    return boundaryCandidate(document.body, ROOT_NODE_ID, 0, clientY);
  }

  function candidateAtPoint(clientX, clientY) {
    if (!dragState) return null;
    if (dragState.sourceEl.parentElement === document.body && ROOT_NODE_ID) {
      return topLevelCandidate(clientY);
    }
    var hit = document.elementFromPoint(clientX, clientY);
    var hovered =
      hit && hit.closest ? hit.closest("[data-node-id]") : null;
    if (!hovered) return null;

    // An eligible container's center means "inside"; its leading/trailing edge
    // means "beside it" in the container above. This makes both reparent and
    // sibling reorder available without a mode switch.
    if (canDropInto(hovered)) {
      var siblingParent = parentNodeElement(hovered);
      if (
        siblingParent &&
        canDropInto(siblingParent) &&
        nearFlowEdge(hovered, siblingParent, clientX, clientY)
      ) {
        return boundaryCandidate(
          siblingParent,
          nodeId(siblingParent),
          clientX,
          clientY
        );
      }
      return boundaryCandidate(hovered, nodeId(hovered), clientX, clientY);
    }

    // A leaf (or any point inside the moving subtree) resolves upward to the
    // nearest legal parent outside the source subtree.
    var parentEl = parentNodeElement(hovered);
    while (parentEl && !canDropInto(parentEl)) {
      parentEl = parentNodeElement(parentEl);
    }
    return parentEl
      ? boundaryCandidate(parentEl, nodeId(parentEl), clientX, clientY)
      : null;
  }

  function positionGrip(el) {
    if (!grip) return;
    var rect = el.getBoundingClientRect();
    grip.style.top = Math.max(2, rect.top + window.scrollY - 30) + "px";
    grip.style.left =
      Math.max(2, Math.min(document.documentElement.scrollWidth - 30, rect.right + window.scrollX + 6)) +
      "px";
  }

  function removeGrip() {
    if (grip) { grip.remove(); grip = null; }
  }

  function positionResizeHandles(el) {
    if (!el || resizeHandles.length === 0) return;
    var rect = el.getBoundingClientRect();
    var docLeft = rect.left + window.scrollX;
    var docTop = rect.top + window.scrollY;
    for (var i = 0; i < resizeHandles.length; i++) {
      var handle = resizeHandles[i];
      var axis = handle.getAttribute("data-axis");
      if (axis === "width") {
        handle.style.left = docLeft + rect.width - 6 + "px";
        handle.style.top = docTop + rect.height / 2 - 6 + "px";
      } else if (axis === "height") {
        handle.style.left = docLeft + rect.width / 2 - 6 + "px";
        handle.style.top = docTop + rect.height - 6 + "px";
      } else {
        handle.style.left = docLeft + rect.width - 6 + "px";
        handle.style.top = docTop + rect.height - 6 + "px";
      }
    }
    if (resizeBadge) {
      resizeBadge.style.left = docLeft + rect.width + 10 + "px";
      resizeBadge.style.top = docTop + rect.height + 10 + "px";
      resizeBadge.textContent =
        Math.round(rect.width) + " × " + Math.round(rect.height) + " px";
    }
  }

  function positionSelectionControls(el) {
    if (!el) return;
    if (grip) positionGrip(el);
    positionResizeHandles(el);
  }

  function removeResizeControls() {
    for (var i = 0; i < resizeHandles.length; i++) {
      resizeHandles[i].remove();
    }
    resizeHandles = [];
    if (resizeBadge) {
      resizeBadge.remove();
      resizeBadge = null;
    }
  }

  function restoreInlineDimension(el, property, value, priority) {
    if (value) {
      el.style.setProperty(property, value, priority || "");
    } else {
      el.style.removeProperty(property);
    }
  }

  function startResize(event, el, id, axis) {
    if (event.button !== 0 || resizeState || dragState) return;
    event.preventDefault();
    event.stopPropagation();
    var computed = window.getComputedStyle(el);
    var cssWidth = parseFloat(computed.width);
    var cssHeight = parseFloat(computed.height);
    if (!Number.isFinite(cssWidth) || !Number.isFinite(cssHeight)) return;
    resizeState = {
      nodeId: id,
      sourceEl: el,
      axis: axis,
      startX: event.clientX,
      startY: event.clientY,
      startWidth: cssWidth,
      startHeight: cssHeight,
      widthPx: null,
      heightPx: null,
      moved: false,
      inlineWidth: el.style.getPropertyValue("width"),
      inlineWidthPriority: el.style.getPropertyPriority("width"),
      inlineHeight: el.style.getPropertyValue("height"),
      inlineHeightPriority: el.style.getPropertyPriority("height")
    };
    resizeBadge = document.createElement("div");
    resizeBadge.className = "lumen-resize-badge";
    document.body.appendChild(resizeBadge);
    document.body.classList.add("lumen-resizing");
    positionResizeHandles(el);
  }

  function updateResize(event) {
    if (!resizeState) return;
    var dx = event.clientX - resizeState.startX;
    var dy = event.clientY - resizeState.startY;
    if (resizeState.axis === "width" || resizeState.axis === "both") {
      resizeState.widthPx = Math.max(16, resizeState.startWidth + dx);
      resizeState.sourceEl.style.width = resizeState.widthPx + "px";
    }
    if (resizeState.axis === "height" || resizeState.axis === "both") {
      resizeState.heightPx = Math.max(16, resizeState.startHeight + dy);
      resizeState.sourceEl.style.height = resizeState.heightPx + "px";
    }
    resizeState.moved =
      Math.abs(dx) >= 1 || Math.abs(dy) >= 1;
    positionResizeHandles(resizeState.sourceEl);
    scheduleSelectedInfo();
  }

  function finishResize(commit) {
    if (!resizeState) return;
    var state = resizeState;
    resizeState = null;
    restoreInlineDimension(
      state.sourceEl,
      "width",
      state.inlineWidth,
      state.inlineWidthPriority
    );
    restoreInlineDimension(
      state.sourceEl,
      "height",
      state.inlineHeight,
      state.inlineHeightPriority
    );
    document.body.classList.remove("lumen-resizing");
    if (resizeBadge) {
      resizeBadge.remove();
      resizeBadge = null;
    }
    positionSelectionControls(state.sourceEl);
    scheduleSelectedInfo();
    if (commit && state.moved) {
      post("resize-node", {
        nodeId: state.nodeId,
        widthPx: state.widthPx === null ? null : Math.round(state.widthPx),
        heightPx: state.heightPx === null ? null : Math.round(state.heightPx)
      });
    }
  }

  function showResizeHandlesFor(el) {
    removeResizeControls();
    var id = nodeId(el);
    if (!el || !id || !RESIZABLE_NODE_IDS.has(id)) return;
    ["width", "height", "both"].forEach(function (axis) {
      var handle = document.createElement("button");
      handle.type = "button";
      handle.className = "lumen-resize-handle";
      handle.setAttribute("data-axis", axis);
      handle.setAttribute(
        "aria-label",
        "Resize " + id + " " + (axis === "both" ? "width and height" : axis)
      );
      handle.setAttribute(
        "title",
        axis === "both" ? "Resize width and height" : "Resize " + axis
      );
      handle.addEventListener("mousedown", function (event) {
        startResize(event, el, id, axis);
      });
      document.body.appendChild(handle);
      resizeHandles.push(handle);
    });
    positionResizeHandles(el);
  }

  function createGhost(el) {
    var clone = el.cloneNode(true);
    clone.removeAttribute("data-node-id");
    Array.prototype.forEach.call(
      clone.querySelectorAll("[data-node-id]"),
      function (child) { child.removeAttribute("data-node-id"); }
    );
    clone.classList.remove("lumen-selected", "lumen-hover", "lumen-editing");
    clone.classList.add("lumen-drag-ghost");
    var rect = el.getBoundingClientRect();
    clone.style.width = Math.min(rect.width, 280) + "px";
    clone.style.height = Math.min(rect.height, 180) + "px";
    document.body.appendChild(clone);
    return clone;
  }

  function positionGhost(clientX, clientY) {
    if (!dragGhost) return;
    dragGhost.style.left = clientX + 14 + "px";
    dragGhost.style.top = clientY + 14 + "px";
  }

  function clearDropVisuals() {
    if (dropMarker) { dropMarker.remove(); dropMarker = null; }
    if (dropParentEl) {
      dropParentEl.classList.remove("lumen-drop-parent");
      dropParentEl = null;
    }
  }

  function showDropCandidate(candidate) {
    clearDropVisuals();
    if (!candidate) return;
    var parentRect = candidate.parentEl.getBoundingClientRect();
    var before = candidate.children[candidate.index] || null;
    var last = candidate.children[candidate.children.length - 1] || null;
    var beforeRect = before ? before.getBoundingClientRect() : null;
    var lastRect = last ? last.getBoundingClientRect() : null;
    dropMarker = document.createElement("div");
    dropMarker.className =
      "lumen-drop-marker " + (candidate.axis === "row" ? "is-row" : "is-block");
    if (candidate.axis === "row") {
      var x = beforeRect
        ? beforeRect.left
        : lastRect
          ? lastRect.right
          : parentRect.left + 8;
      dropMarker.style.left = x + window.scrollX - 1.5 + "px";
      dropMarker.style.top = parentRect.top + window.scrollY + 8 + "px";
      dropMarker.style.width = "3px";
      dropMarker.style.height = Math.max(18, parentRect.height - 16) + "px";
    } else {
      var y = beforeRect
        ? beforeRect.top
        : lastRect
          ? lastRect.bottom
          : parentRect.top + 8;
      dropMarker.style.left = parentRect.left + window.scrollX + 8 + "px";
      dropMarker.style.top = y + window.scrollY - 1.5 + "px";
      dropMarker.style.width = Math.max(18, parentRect.width - 16) + "px";
      dropMarker.style.height = "3px";
    }
    document.body.appendChild(dropMarker);
    if (candidate.parentEl !== document.body) {
      dropParentEl = candidate.parentEl;
      dropParentEl.classList.add("lumen-drop-parent");
    }
  }

  function finishDrag(commit) {
    if (!dragState) return;
    var destination = dragState.destination;
    dragState.sourceEl.style.opacity = dragState.sourceOpacity;
    if (dragGhost) { dragGhost.remove(); dragGhost = null; }
    clearDropVisuals();
    if (grip) {
      grip.style.cursor = "grab";
    }
    document.body.classList.remove("lumen-dragging");
    var nodeIdToMove = dragState.nodeId;
    dragState = null;
    if (commit && destination) {
      post("move-node", {
        nodeId: nodeIdToMove,
        newParentNodeId: destination.newParentNodeId,
        index: destination.index
      });
    }
  }

  function showGripFor(el) {
    removeGrip();
    var id = nodeId(el);
    if (!el || !id || !MOVABLE_NODE_IDS.has(id)) return;
    grip = document.createElement("div");
    grip.className = "lumen-grip";
    grip.textContent = "\\u22ee\\u22ee";
    grip.setAttribute("role", "button");
    grip.setAttribute("aria-label", "Drag to move " + id);
    grip.setAttribute("title", "Drag to reorder or move into another container");
    document.body.appendChild(grip);
    positionGrip(el);
    grip.addEventListener("mousedown", function (event) {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      dragState = {
        nodeId: id,
        sourceEl: el,
        sourceOpacity: el.style.opacity,
        destination: null
      };
      dragGhost = createGhost(el);
      positionGhost(event.clientX, event.clientY);
      el.style.opacity = ".35";
      grip.style.cursor = "grabbing";
      document.body.classList.add("lumen-dragging");
    });
  }

  document.addEventListener("mousemove", function (event) {
    if (resizeState) {
      event.preventDefault();
      updateResize(event);
      return;
    }
    if (dragState) {
      event.preventDefault();
      positionGhost(event.clientX, event.clientY);
      dragState.destination = candidateAtPoint(event.clientX, event.clientY);
      showDropCandidate(dragState.destination);
    }
  });

  document.addEventListener("mouseup", function () {
    if (resizeState) {
      finishResize(true);
    } else {
      finishDrag(true);
    }
  });

  document.addEventListener(
    "keydown",
    function (event) {
      if (event.key === "Escape" && dragState) {
        event.preventDefault();
        finishDrag(false);
      } else if (event.key === "Escape" && resizeState) {
        event.preventDefault();
        finishResize(false);
      }
    },
    true
  );

  window.addEventListener(
    "scroll",
    function () {
      if (selected) positionSelectionControls(selected);
      scheduleSelectedInfo();
      if (lastAnnotations) renderAnnotations(lastAnnotations);
      if (editingSession) editingSession.refreshSelection();
    },
    { passive: true }
  );
  window.addEventListener(
    "resize",
    function () {
      if (selected) positionSelectionControls(selected);
      scheduleSelectedInfo();
      hideHover();
      // Badges are drawn in DOCUMENT coordinates, so a scroll does not move them — but
      // a reflow does. Re-measure from the last payload the shell sent rather than
      // leaving stale rectangles behind.
      if (lastAnnotations) renderAnnotations(lastAnnotations);
      if (editingSession) editingSession.refreshSelection();
    },
    { passive: true }
  );
  window.addEventListener("blur", function () {
    if (dragState) finishDrag(false);
    if (resizeState) finishResize(false);
  });

  post("ready", {});
})();
"""


def _script_json(value: Any) -> str:
    """Compact JSON safe to interpolate inside an HTML script body."""
    return (
        json.dumps(value, ensure_ascii=True, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _bridge_page_routes(web_doc: dict[str, Any] | None) -> dict[str, str]:
    """This document's `{route: page_id}` map — the whole site, not one page.

    Deliberately NOT part of `_bridge_page_capabilities` (which is page-scoped
    and short-circuits when the rendered page is missing): a route map that
    omitted the pages you can navigate TO would be useless.
    """
    pages = web_doc.get("pages") if isinstance(web_doc, dict) else None
    return {
        page["route"]: page["id"]
        for page in (pages or [])
        if isinstance(page, dict)
        and isinstance(page.get("id"), str)
        and isinstance(page.get("route"), str)
    }


def _bridge_node_names(
    web_doc: dict[str, Any] | None,
    page_id: str,
    fragment_meta: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Ruling R-A4/R-A5: the display name of every node on the rendered page, in the
    shared order (:func:`lumen_api.main._web_node_label`), baked into the script so the
    hover chip can name a band without a round trip.

    A node with nothing cheap to say falls back to its KIND rather than dropping out of
    the map: the script's own fallback is the raw tag name, and a chip reading
    "Container" is worth more to a marketer than one reading "div".

    Unlike :func:`_bridge_page_capabilities` this does NOT fall back to the first page
    when ``page_id`` is unknown — a name map for the wrong page would put the wrong
    words on the wrong band, which is worse than no words at all.
    """
    from lumen_api.main import _web_node_label  # shared order; import here to avoid a cycle

    pages = web_doc.get("pages") if isinstance(web_doc, dict) else None
    page = next(
        (
            candidate
            for candidate in (pages or [])
            if isinstance(candidate, dict) and candidate.get("id") == page_id
        ),
        None,
    )
    raw_nodes = (page or {}).get("nodes")
    nodes = raw_nodes if isinstance(raw_nodes, dict) else {}
    names: dict[str, str] = {}
    for node_id, node in nodes.items():
        if not isinstance(node_id, str) or not isinstance(node, dict):
            continue
        label = _web_node_label(node, nodes, fragment_meta)
        names[node_id] = label or str(node.get("kind") or "node").capitalize()
    return names


def _bridge_page_capabilities(
    web_doc: dict[str, Any] | None, page_id: str
) -> tuple[list[str], list[str], list[str], str]:
    pages = web_doc.get("pages") if isinstance(web_doc, dict) else None
    page = next(
        (
            candidate
            for candidate in (pages or [])
            if isinstance(candidate, dict) and candidate.get("id") == page_id
        ),
        None,
    )
    if page is None and isinstance(pages, list):
        page = next((candidate for candidate in pages if isinstance(candidate, dict)), None)
    if page is None:
        return [], [], [], ""
    nodes = page.get("nodes")
    nodes = nodes if isinstance(nodes, dict) else {}
    root_id = page.get("root") if isinstance(page.get("root"), str) else "root"
    # `fragment` is here and in NEITHER set below — founder ruling D-F3 (Option A, top-level
    # reordering only), wired at the one place the three allowlists are spelled. A whole cloned
    # band can be moved up or down the page; it can never be manually resized (its proportions
    # ARE the clone), never be a drop target (an ordinary node dropped inside it would be an
    # internal edit of somebody else's section), and it stays a leaf in the engine, so there is
    # nothing inside it to re-lay-out or detach. Pinned by `tests/test_fragment_mobility.py`.
    movable_kinds = {
        "section",
        "container",
        "text",
        "button",
        "image",
        "custom_component",
        "fragment",
    }
    parent_kinds = {"section", "container"}
    resizable_kinds = {
        "container",
        "text",
        "button",
        "image",
        "custom_component",
    }
    movable = sorted(
        node_id
        for node_id, node in nodes.items()
        if isinstance(node_id, str)
        and isinstance(node, dict)
        and node.get("kind") in movable_kinds
        and node_id != root_id
    )
    drop_parents = sorted(
        node_id
        for node_id, node in nodes.items()
        if isinstance(node_id, str)
        and isinstance(node, dict)
        and node.get("kind") in parent_kinds
        and node_id != root_id
    )
    resizable = sorted(
        node_id
        for node_id, node in nodes.items()
        if isinstance(node_id, str)
        and isinstance(node, dict)
        and node.get("kind") in resizable_kinds
        and node_id != root_id
    )
    return movable, drop_parents, resizable, root_id


def render_bridge_script(
    nonce: str,
    web_doc: dict[str, Any] | None = None,
    page_id: str = "home",
    fragment_meta: dict[str, Any] | None = None,
) -> str:
    """The bridge script with the shell's nonce baked in. Raises ValueError on
    a nonce outside the strict charset — the caller maps that to a 422."""
    if not NONCE_PATTERN.match(nonce or ""):
        raise ValueError("bridge nonce must match ^[A-Za-z0-9-]{8,64}$")
    movable, drop_parents, resizable, root_id = _bridge_page_capabilities(
        web_doc, page_id
    )
    return (
        _BRIDGE_V0_TEMPLATE.replace("__LUMEN_BRIDGE_NONCE__", nonce)
        .replace("__LUMEN_MOVABLE_NODE_IDS__", _script_json(movable))
        .replace("__LUMEN_DROP_PARENT_NODE_IDS__", _script_json(drop_parents))
        .replace("__LUMEN_RESIZABLE_NODE_IDS__", _script_json(resizable))
        .replace("__LUMEN_ROOT_NODE_ID__", _script_json(root_id))
        .replace("__LUMEN_PAGE_ROUTES__", _script_json(_bridge_page_routes(web_doc)))
        .replace(
            "__LUMEN_NODE_NAMES__",
            _script_json(_bridge_node_names(web_doc, page_id, fragment_meta)),
        )
    )
