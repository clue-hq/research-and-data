# Sidebar project/chat name marquee — 2026-09-12

Founder requested consistent row sizing and one forward hover pass for overflowing
project and chat names, with the beginning rolling into place instead of reversing.

Added a shared SidebarMarqueeLabel to ProjectSidebarTree. ResizeObserver measures
the actual text and available width (also catches renames, fonts and layout changes).
Only overflowing labels get a second, aria-hidden copy. A single linear CSS pass
moves by the text width plus a 24px gap; the duplicate ends at the original's start,
then the original replaces it seamlessly. Remains stopped until another hover or
keyboard focus. Respects reduced motion, keeps full-name title and accessible text,
and preserves existing 32px rows, fixed icons, controls and status badges.

Browser verification used a temporary authenticated route rendering the real sidebar
tree with synthetic labels; no project/chat data was changed. At 224px width, long
project/chat/status rows overflowed and short labels did not. All rows remained 32px.
Pointer sampling showed forward translation through -246.8px of a 254.98px cycle,
then exact zero while hover continued over four later samples. Keyboard focus starts
the same single-pass animation for chats and finishes at zero. Accessible names do
not duplicate. At 600px width all copies/overflow flags disappeared; at 180px long
status labels scrolled and renamed short labels stopped. Screenshot reviewed.

Tooling notes: CUA lacks locator.hover; used a pointer click on the no-op test project
to exercise its hover state. Its read-only DOM scope lacks performance.now; sampled
layout without that clock instead. Temporary check route removed after verification.
React review: effect observer disconnects on unmount; observes both relevant nodes;
no transport logic, new packages or model/server changes.

Closing checks: design-system build, lint and production build all passed after the
temporary route was removed. Only the two existing canvasOperations unused-function
warnings remain; git diff --check passed. The live Brand Context sidebar's existing
short project/chat names remain static at 32px height. Test tab closed, user tab left
on Brand Context with the project expanded. Committing/pushing under standing request.
