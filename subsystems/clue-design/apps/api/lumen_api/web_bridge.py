"""Bridge for the website-mode editor iframe (v1).

The renderer's editor mode injects this script into the srcdoc document. It
does the following and nothing else: hover/selection outlines over
`data-node-id` elements, click-to-select posted to the parent shell,
suppression of link navigation AND invoker-command buttons inside the canvas,
(v1) dblclick contenteditable text editing on Text nodes — commit posts
`{type:"text-commit", nodeId, html}` and the SERVER canonicalizes the HTML
through the SetText sanitizer, so the bridge payload is never trusted as
markup — and two parent-driven inbound actions: component preview
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

v3 adds top-level section drag-reorder: a grip appears on the selected
top-level section; dragging it shows an insertion line and, on drop, posts a
`{type:"move-section", nodeId, boundary}` intent (the boundary index among the
current top-level sections) which the shell turns into a MoveNode op.
"""

import re

NONCE_PATTERN = re.compile(r"^[A-Za-z0-9-]{8,64}$")

BRIDGE_CHANNEL = "lumen-web-bridge"

_BRIDGE_V0_TEMPLATE = """
(function () {
  var NONCE = "__LUMEN_BRIDGE_NONCE__";
  var CHANNEL = "lumen-web-bridge";
  var selected = null;
  var hoverEl = null;

  var editing = null;
  var editingOriginal = "";

  var style = document.createElement("style");
  style.textContent =
    "[data-node-id].lumen-hover{outline:1.5px dashed rgba(79,111,255,0.7);outline-offset:2px;}" +
    "[data-node-id].lumen-selected{outline:2px solid rgba(79,111,255,0.95);outline-offset:2px;}" +
    "[data-node-id].lumen-editing{outline:2px solid rgba(34,197,146,0.95);outline-offset:2px;cursor:text;}";
  document.head.appendChild(style);

  function nodeInfo(el) {
    if (!el) return null;
    return {
      nodeId: el.getAttribute("data-node-id"),
      tag: el.tagName.toLowerCase(),
      tv: el.getAttribute("data-tv"),
      btn: el.getAttribute("data-btn"),
      text: (el.textContent || "").trim().slice(0, 60)
    };
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

  function setSelected(el) {
    if (selected) selected.classList.remove("lumen-selected");
    selected = el;
    if (el) {
      el.classList.remove("lumen-hover");
      el.classList.add("lumen-selected");
    }
    post("select", { node: nodeInfo(el) });
    showGripFor(el);
  }

  document.addEventListener("mouseover", function (event) {
    var el =
      event.target && event.target.closest
        ? event.target.closest("[data-node-id]")
        : null;
    if (hoverEl && hoverEl !== el) hoverEl.classList.remove("lumen-hover");
    if (el && el !== selected) el.classList.add("lumen-hover");
    hoverEl = el;
  });

  document.addEventListener("mouseout", function () {
    if (hoverEl) {
      hoverEl.classList.remove("lumen-hover");
      hoverEl = null;
    }
  });

  // Capture phase: links in the canvas must never navigate the iframe, and
  // element clicks become selection.
  document.addEventListener(
    "click",
    function (event) {
      var anchor =
        event.target && event.target.closest ? event.target.closest("a") : null;
      if (anchor) event.preventDefault();
      var cmdBtn =
        event.target && event.target.closest
          ? event.target.closest("button[commandfor]")
          : null;
      if (cmdBtn) event.preventDefault();
      // Clicks inside the element being edited belong to the caret, not to
      // selection; clicking anywhere else blurs (committing) first.
      if (editing && editing.contains(event.target)) return;
      var el =
        event.target && event.target.closest
          ? event.target.closest("[data-node-id]")
          : null;
      setSelected(el);
    },
    true
  );

  // v1: dblclick a Text node (data-tv) to edit its inline content in place.
  function stopEditing(commit) {
    if (!editing) return;
    var el = editing;
    editing = null;
    el.removeAttribute("contenteditable");
    el.classList.remove("lumen-editing");
    if (commit) {
      if (el.innerHTML !== editingOriginal) {
        post("text-commit", {
          nodeId: el.getAttribute("data-node-id"),
          html: el.innerHTML
        });
      }
    } else {
      el.innerHTML = editingOriginal;
    }
    editingOriginal = "";
  }

  document.addEventListener(
    "dblclick",
    function (event) {
      var el =
        event.target && event.target.closest
          ? event.target.closest("[data-node-id][data-tv]")
          : null;
      if (!el || editing === el) return;
      stopEditing(true);
      editing = el;
      editingOriginal = el.innerHTML;
      el.classList.remove("lumen-hover");
      el.classList.add("lumen-editing");
      el.setAttribute("contenteditable", "true");
      el.focus();
      post("edit-start", { nodeId: el.getAttribute("data-node-id") });
    },
    true
  );

  document.addEventListener(
    "blur",
    function (event) {
      if (editing && event.target === editing) stopEditing(true);
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
    if (event.key === "Escape" && selected) setSelected(null);
  });

  window.addEventListener("message", function (event) {
    var data = event.data || {};
    if (data.channel !== CHANNEL || data.nonce !== NONCE) return;
    if (data.type === "clear" && selected) {
      selected.classList.remove("lumen-selected");
      selected = null;
      removeGrip();
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
    if (data.type === "select-node") {
      var target = document.querySelector(
        '[data-node-id="' + CSS.escape(String(data.nodeId || "")) + '"]'
      );
      if (target) setSelected(target);
    }
  });

  // v3: drag-reorder for top-level sections. A grip appears on the selected
  // section; dragging shows an insertion line and posts a move-section
  // intent with the boundary index among current top-level sections.
  var grip = null;
  var dropLine = null;
  var dragState = null;

  var structureStyle = document.createElement("style");
  structureStyle.textContent =
    ".lumen-grip{position:absolute;z-index:2147483000;display:flex;align-items:center;" +
    "justify-content:center;width:28px;height:28px;border-radius:8px;cursor:grab;" +
    "background:rgba(79,111,255,0.95);color:#fff;font-size:14px;user-select:none;}" +
    ".lumen-drop-line{position:absolute;left:8px;right:8px;height:3px;border-radius:2px;" +
    "background:rgba(79,111,255,0.95);z-index:2147483000;pointer-events:none;}";
  document.head.appendChild(structureStyle);

  function topSections() {
    return Array.prototype.slice.call(document.body.children).filter(function (el) {
      return el.hasAttribute && el.hasAttribute("data-node-id");
    });
  }

  function positionGrip(el) {
    if (!grip) return;
    var rect = el.getBoundingClientRect();
    grip.style.top = rect.top + window.scrollY + 8 + "px";
    grip.style.left = rect.right + window.scrollX - 40 + "px";
  }

  function removeGrip() {
    if (grip) { grip.remove(); grip = null; }
  }

  function showGripFor(el) {
    removeGrip();
    if (!el || el.parentElement !== document.body) return;
    grip = document.createElement("div");
    grip.className = "lumen-grip";
    grip.textContent = "\\u2261";
    document.body.appendChild(grip);
    positionGrip(el);
    grip.addEventListener("mousedown", function (event) {
      event.preventDefault();
      dragState = { nodeId: el.getAttribute("data-node-id"), boundary: null };
      dropLine = document.createElement("div");
      dropLine.className = "lumen-drop-line";
      document.body.appendChild(dropLine);
      grip.style.cursor = "grabbing";
    });
  }

  function dragBoundary(clientY) {
    var sections = topSections();
    for (var i = 0; i < sections.length; i++) {
      var rect = sections[i].getBoundingClientRect();
      if (clientY < rect.top + rect.height / 2) {
        return { index: i, y: rect.top + window.scrollY };
      }
    }
    var last = sections[sections.length - 1];
    var bottom = last ? last.getBoundingClientRect().bottom : 0;
    return { index: sections.length, y: bottom + window.scrollY };
  }

  document.addEventListener("mousemove", function (event) {
    if (!dragState || !dropLine) return;
    var boundary = dragBoundary(event.clientY);
    dragState.boundary = boundary.index;
    dropLine.style.top = boundary.y - 2 + "px";
  });

  document.addEventListener("mouseup", function () {
    if (!dragState) return;
    if (typeof dragState.boundary === "number") {
      post("move-section", { nodeId: dragState.nodeId, boundary: dragState.boundary });
    }
    if (dropLine) { dropLine.remove(); dropLine = null; }
    if (grip) grip.style.cursor = "grab";
    dragState = null;
  });

  document.addEventListener(
    "keydown",
    function (event) {
      if (event.key === "Escape" && dragState) {
        if (dropLine) { dropLine.remove(); dropLine = null; }
        dragState = null;
      }
    },
    true
  );

  window.addEventListener(
    "scroll",
    function () {
      if (grip && selected) positionGrip(selected);
    },
    { passive: true }
  );

  post("ready", {});
})();
"""


def render_bridge_script(nonce: str) -> str:
    """The bridge script with the shell's nonce baked in. Raises ValueError on
    a nonce outside the strict charset — the caller maps that to a 422."""
    if not NONCE_PATTERN.match(nonce or ""):
        raise ValueError("bridge nonce must match ^[A-Za-z0-9-]{8,64}$")
    return _BRIDGE_V0_TEMPLATE.replace("__LUMEN_BRIDGE_NONCE__", nonce)
