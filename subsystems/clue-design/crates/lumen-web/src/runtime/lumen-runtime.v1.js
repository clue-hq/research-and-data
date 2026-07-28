/* lumen-runtime v1 — the ONE versioned platform interaction runtime.
   Supplies only what the browser cannot: an Invoker Commands polyfill
   (button[commandfor][command]) for engines without native support, and
   dialog light-dismiss (backdrop click closes) for engines without
   `closedby`. Zero page-specific code; idempotent under re-injection. */
(function () {
  if (window.__lumenRuntimeV1) return;
  window.__lumenRuntimeV1 = 1;
  var nativeInvokers = "command" in HTMLButtonElement.prototype;
  if (!nativeInvokers) {
    document.addEventListener("click", function (event) {
      var origin = event.target instanceof Element ? event.target : null;
      var button = origin ? origin.closest("button[commandfor][command]") : null;
      if (!button || event.defaultPrevented) return;
      var target = document.getElementById(button.getAttribute("commandfor"));
      if (!target || target.tagName !== "DIALOG") return;
      var command = button.getAttribute("command");
      if (command === "show-modal" && !target.open) target.showModal();
      else if (command === "close" && target.open) target.close();
    });
  }
  var nativeClosedBy = "closedBy" in HTMLDialogElement.prototype;
  if (!nativeClosedBy) {
    document.addEventListener("click", function (event) {
      var dialog = event.target;
      if (!(dialog instanceof HTMLDialogElement) || !dialog.open) return;
      var rect = dialog.getBoundingClientRect();
      var inside =
        event.clientX >= rect.left && event.clientX <= rect.right &&
        event.clientY >= rect.top && event.clientY <= rect.bottom;
      if (!inside) dialog.close();
    });
  }
})();
