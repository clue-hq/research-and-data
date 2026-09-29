/* lumen-runtime v2 — the ONE versioned platform interaction runtime.
   Supplies only what the browser cannot: an Invoker Commands polyfill
   (button[commandfor][command]) for engines without native support, and
   dialog light-dismiss (backdrop click closes) for engines without
   `closedby`. Zero page-specific code; idempotent under re-injection.
   v2 adds: carousel arrows/autoplay and accessible tabs. */
(function () {
  if (window.__lumenRuntimeV2) return;
  window.__lumenRuntimeV2 = 2;
  var nativeInvokers = "command" in HTMLButtonElement.prototype;
  if (!nativeInvokers) {
    document.addEventListener("click", function (event) {
      var origin = event.target instanceof Element ? event.target : null;
      var button = origin ? origin.closest("button[data-lumen-command][commandfor][command]") : null;
      if (!button || event.defaultPrevented) return;
      var target = document.getElementById(button.getAttribute("commandfor"));
      if (!target || target.tagName !== "DIALOG" || !target.hasAttribute('data-lumen-dialog')) return;
      var command = button.getAttribute("command");
      if (command === "show-modal" && !target.open) target.showModal();
      else if (command === "close" && target.open) target.close();
    });
  }
  var nativeClosedBy = "closedBy" in HTMLDialogElement.prototype;
  if (!nativeClosedBy) {
    document.addEventListener("click", function (event) {
      var dialog = event.target;
      if (!(dialog instanceof HTMLDialogElement) || !dialog.open || !dialog.hasAttribute('data-lumen-dialog')) return;
      var rect = dialog.getBoundingClientRect();
      var inside =
        event.clientX >= rect.left && event.clientX <= rect.right &&
        event.clientY >= rect.top && event.clientY <= rect.bottom;
      if (!inside) dialog.close();
    });
  }

  var reducedMotion =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Carousel: arrows page by ~80% of the track width; autoplay steps and
  // wraps, pausing on hover/focus. Reduced motion disables autoplay.
  function initCarousel(root) {
    var track = root.querySelector(".lumen-carousel-track");
    if (!track) return;
    function page(dir) {
      track.scrollBy({
        left: dir * track.clientWidth * 0.8,
        behavior: reducedMotion ? "auto" : "smooth"
      });
    }
    root.querySelectorAll(".lumen-carousel-arrow").forEach(function (arrow) {
      arrow.addEventListener("click", function () {
        page(arrow.getAttribute("data-dir") === "prev" ? -1 : 1);
      });
    });
    var seconds = parseInt(root.getAttribute("data-autoplay-s") || "0", 10);
    if (seconds > 0 && !reducedMotion) {
      var paused = false;
      root.addEventListener("mouseenter", function () { paused = true; });
      root.addEventListener("mouseleave", function () { paused = false; });
      root.addEventListener("focusin", function () { paused = true; });
      root.addEventListener("focusout", function () { paused = false; });
      setInterval(function () {
        if (paused || !track.isConnected) return;
        var atEnd = track.scrollLeft + track.clientWidth >= track.scrollWidth - 4;
        if (atEnd) track.scrollTo({ left: 0, behavior: "auto" });
        else page(1);
      }, seconds * 1000);
    }
  }

  // Tabs: selection toggles aria-selected + panel hidden; arrow keys move.
  function initTabs(root) {
    var tabs = Array.prototype.slice.call(root.querySelectorAll('[role="tab"]')).filter(function (tab) {
      return tab.closest('[data-lumen-tabs]') === root;
    });
    var panels = Array.prototype.slice.call(root.children).filter(function (panel) {
      return panel.getAttribute('role') === 'tabpanel';
    });
    function select(tab) {
      tabs.forEach(function (other) {
        var selected = other === tab;
        other.setAttribute("aria-selected", selected ? "true" : "false");
        other.tabIndex = selected ? 0 : -1;
        var panel = panels.find(function (candidate) {
          return candidate.id === other.getAttribute("aria-controls");
        });
        if (panel) panel.hidden = !selected;
      });
      tab.focus({ preventScroll: true });
    }
    tabs.forEach(function (tab, index) {
      tab.addEventListener("click", function (event) {
        if (!event.defaultPrevented) select(tab);
      });
      tab.addEventListener("keydown", function (event) {
        var delta = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
        if (!delta) return;
        event.preventDefault();
        select(tabs[(index + delta + tabs.length) % tabs.length]);
      });
    });
  }

  function initAll() {
    document.querySelectorAll("[data-lumen-carousel]").forEach(initCarousel);
    document.querySelectorAll("[data-lumen-tabs]").forEach(initTabs);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }
})();
