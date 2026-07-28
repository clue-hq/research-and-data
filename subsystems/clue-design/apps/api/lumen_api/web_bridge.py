"""Bridge v0 for the website-mode editor iframe.

The renderer's editor mode injects this script into the srcdoc document. It
does three things and nothing else: hover/selection outlines over
`data-node-id` elements, click-to-select posted to the parent shell, and
suppression of link navigation inside the canvas. Security posture:

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

  var style = document.createElement("style");
  style.textContent =
    "[data-node-id].lumen-hover{outline:1.5px dashed rgba(79,111,255,0.7);outline-offset:2px;}" +
    "[data-node-id].lumen-selected{outline:2px solid rgba(79,111,255,0.95);outline-offset:2px;}";
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
      var el =
        event.target && event.target.closest
          ? event.target.closest("[data-node-id]")
          : null;
      setSelected(el);
    },
    true
  );

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && selected) setSelected(null);
  });

  window.addEventListener("message", function (event) {
    var data = event.data || {};
    if (data.channel !== CHANNEL || data.nonce !== NONCE) return;
    if (data.type === "clear" && selected) {
      selected.classList.remove("lumen-selected");
      selected = null;
    }
  });

  post("ready", {});
})();
"""


def render_bridge_script(nonce: str) -> str:
    """The bridge script with the shell's nonce baked in. Raises ValueError on
    a nonce outside the strict charset — the caller maps that to a 422."""
    if not NONCE_PATTERN.match(nonce or ""):
        raise ValueError("bridge nonce must match ^[A-Za-z0-9-]{8,64}$")
    return _BRIDGE_V0_TEMPLATE.replace("__LUMEN_BRIDGE_NONCE__", nonce)
