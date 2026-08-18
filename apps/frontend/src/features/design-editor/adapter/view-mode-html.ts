/**
 * W4 addendum — the pure decisions behind the view-mode canvas.
 *
 * Founder rulings (2026-08-19):
 *
 * 1. **Edit OFF → the canvas is an actual website.** No hover rectangles, no
 *    selection outlines, no editor chrome of any kind. All of that chrome comes
 *    from the OPT-IN selection bridge (`bridge=1&nonce=…`), so view mode simply
 *    fetches the same render endpoint WITHOUT the bridge and mounts the clean
 *    standalone page the server already returns.
 * 2. **View-mode links behave like a Figma preview.** An ABSOLUTE link opens a
 *    new tab — including links the author did not mark "open in new tab" — a
 *    `#fragment` link scrolls the preview in place, and every other relative
 *    link is inert. Two mechanisms, both decisions about the HTML rather than
 *    about the anchors: one `<base target="_blank">` for the new-tab half, and
 *    one injected classifier script ({@link VIEW_MODE_LINK_SCRIPT}) that
 *    intercepts the other two. The base tag alone was not enough — a bare
 *    `<base target="_blank">` sends `#pricing` and `/story` to a new tab on the
 *    APP's origin (the iframe inherits the parent's base URL), so a fragment
 *    link opened the editor in a second window instead of scrolling.
 *
 * Edit ON is untouched: today's bridged editor surface, exactly as it is.
 *
 * Both functions are pure so they are testable under this repo's renderer-free
 * runner (`tsx --test`, node:test) — the same extraction pattern as
 * `adapter/custom-component-form.ts` (W4.7) and
 * `adapter/rich-text-link-section.ts` (W4.8b).
 */

/** The one tag view mode injects. `target="_blank"` on `<base>` is the default
 * target for every link in the document, so an anchor with no `target` of its
 * own opens a new tab; an anchor that already carries `target="_blank"` (the
 * render emits those with `rel="noopener noreferrer"`) is unaffected. */
export const VIEW_MODE_BASE_TAG = '<base target="_blank">';

/**
 * What a click on a view-mode anchor should do, from its `href` alone.
 *
 * Founder ruling (a), 2026-08-19: absolute → new tab, `#fragment` → scroll the
 * preview in place, anything else → inert.
 *
 * This function is SELF-CONTAINED on purpose: its own
 * `Function.prototype.toString()` source is what
 * {@link VIEW_MODE_LINK_SCRIPT} injects into the view document, so the function
 * these tests exercise and the function the iframe runs are the same text. It
 * therefore must not close over module state, import anything, or reference any
 * identifier declared outside its body — a helper referenced from here would be
 * `undefined` inside the frame.
 *
 * The scheme allow-list is CLOSED, not filtered: `http`/`https`/`mailto`/`tel`
 * open a tab and every other scheme (`javascript:`, `data:`, `file:`, …) is
 * inert. Our own href grammar already refuses those on the write path, but view
 * mode renders whatever document the server hands back, so the classifier does
 * not assume the document came through our editor.
 */
export function viewModeLinkAction(href: string): "new-tab" | "scroll" | "inert" {
  const raw = String(href).trim();
  if (raw.charAt(0) === "#") return "scroll";
  const scheme = /^([a-z][a-z0-9+.\-]*):/i.exec(raw);
  if (scheme) {
    const name = scheme[1].toLowerCase();
    if (name === "http" || name === "https") return "new-tab";
    if (name === "mailto" || name === "tel") return "new-tab";
    return "inert";
  }
  if (raw.slice(0, 2) === "//") return "new-tab";
  return "inert";
}

/**
 * The one script view mode injects: a capture-phase click handler carrying
 * {@link viewModeLinkAction}'s own source, so there is one implementation of
 * the rule and zero drift between the tested classifier and the shipped one.
 *
 * Three details are load-bearing:
 *
 * - **Capture phase** (`true`): a rendered document may stop propagation in its
 *   own handlers; the preview's link behaviour must not be cancellable by the
 *   content it is previewing.
 * - **`new-tab` does nothing.** The handler only spends `scroll` and `inert`;
 *   the `<base target="_blank">` above it already opens absolute links, and
 *   calling `window.open` here would fight it (and be popup-blocked).
 * - **The href is read with `getAttribute`**, never `a.href` — the DOM property
 *   resolves against the base URL and would turn `#pricing` into an absolute
 *   app-origin URL before the classifier ever saw the fragment.
 */
export const VIEW_MODE_LINK_SCRIPT =
  `<script>(function(){var classify=${viewModeLinkAction.toString()};` +
  `document.addEventListener("click",function(ev){` +
  `var target=ev.target;` +
  `var anchor=target&&target.closest?target.closest("a[href]"):null;` +
  `if(!anchor)return;` +
  `var href=anchor.getAttribute("href")||"";` +
  `var action=classify(href);` +
  `if(action==="scroll"){ev.preventDefault();` +
  `var id=href.trim().slice(1);` +
  `var el=null;if(id){try{el=document.getElementById(decodeURIComponent(id));}catch(e){el=document.getElementById(id);}}` +
  `if(el)el.scrollIntoView({behavior:"smooth"});` +
  `else if(!id)window.scrollTo({top:0,behavior:"smooth"});}` +
  `else if(action==="inert"){ev.preventDefault();}` +
  `},true);})()</script>`;

const HEAD_OPEN = "<head>";

/**
 * The view document's html: the server's clean render with
 * {@link VIEW_MODE_BASE_TAG} and then {@link VIEW_MODE_LINK_SCRIPT} inserted
 * immediately after the opening `<head>`.
 *
 * First position in the head is deliberate — `<base>` only governs elements
 * that follow it, so it must precede anything the head might contain, and the
 * script follows the base because the base is what it defers the `new-tab`
 * case to.
 *
 * The literal `<head>` is safe to match on because this html is generated by
 * our own core (the render endpoint always emits a bare, unattributed opening
 * head tag). Two consequences fall out of matching the FIRST literal one:
 *
 * - A nested custom-component frame's `srcdoc` holds an html-ESCAPED document
 *   (`&lt;head&gt;`), so it can never be matched — the nested page keeps its
 *   own link behaviour and its own markup, untouched.
 * - A document with no head at all (the empty/error shapes) is returned
 *   UNCHANGED rather than having a head invented for it.
 */
export function viewModeHtml(html: string): string {
  const at = html.indexOf(HEAD_OPEN);
  if (at === -1) return html;
  const after = at + HEAD_OPEN.length;
  return (
    html.slice(0, after) +
    VIEW_MODE_BASE_TAG +
    VIEW_MODE_LINK_SCRIPT +
    html.slice(after)
  );
}

/**
 * The canvas iframe's `sandbox` grants, per mode. One home for the decision so
 * the grants and the reasons behind them cannot drift apart.
 *
 * `allow-scripts` is in BOTH modes and is load-bearing in both: a custom
 * component instance renders as a nested `<iframe sandbox="allow-scripts">`
 * carrying its own runtime scripts, and an ancestor sandbox constrains every
 * nested browsing context — dropping the grant from the outer frame would take
 * the component runtime down with it. And the view document itself loads the
 * Tailwind browser runtime (the server's static CSS has no utility rules, so
 * the runtime is what styles `bg-accent` and friends — see `use-web-render`).
 * View mode is not "the scriptless mode".
 *
 * View mode adds exactly two grants, both required for ruling 2 to actually
 * work:
 *
 * - `allow-popups` — without it a sandboxed document cannot open a new
 *   browsing context at all, so `target="_blank"` is silently dead.
 * - `allow-popups-to-escape-sandbox` — without it the tab that DOES open
 *   inherits this sandbox, and the destination site loads with its own scripts
 *   blocked. The link would "work" and the page would be broken.
 *
 * Edit mode keeps exactly `allow-scripts`: the bridge preventDefaults every
 * anchor click by design, so popups there would be grants with no purpose.
 */
export function canvasSandbox(editing: boolean): string {
  return editing
    ? "allow-scripts"
    : "allow-scripts allow-popups allow-popups-to-escape-sandbox";
}
