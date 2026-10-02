import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const css = read("./account-motion.module.css");

test("account navigation uses a persistent shell and does not unmount the directory for previews", () => {
  const layout = read("../../../app/(protected)/accounts/layout.tsx");
  const shell = read("./accounts-layout-shell.tsx");
  // The platform has no settings feature: the workspace person comes from the
  // protected session (D4 Task 2), not from a settings adapter.
  assert.match(layout, /getProtectedSessionResult\(\)/);
  assert.match(shell, /WorkspaceProfileProvider profile=\{profile\}/);
  assert.match(shell, /hidden=\{!directoryVisible\}/);
  assert.match(shell, /<AccountsScreen accounts=\{accounts\}/);
  for (const file of ["accounts-screen.tsx", "contact-full-screen.tsx", "account-workspace-shell.tsx"]) {
    assert.doesNotMatch(read(`./${file}`), /<ApplicationShell|clue-view-enter|clue-panel-enter/);
  }
});
test("initial rail visibility is responsive in CSS instead of a post-render effect", () => {
  const controller = read("../hooks/use-account-workspace-controller.ts");
  assert.doesNotMatch(controller, /useEffect|setDetailsVisible\(desktop\.matches\)/);
  assert.match(controller, /useSyncExternalStore/);
  assert.match(css, /max-width: 1279px/);
  assert.match(css, /data-visible="auto"/);
  assert.match(read("./account-workspace-shell.tsx"), /inert=\{visible === false\}/);
});
test("page entries fade briefly without moving or scaling the text", () => {
  const keyframes = css.slice(css.indexOf("@keyframes pageEntry"), css.indexOf(".pageEntry"));
  assert.doesNotMatch(keyframes, /transform|translate|scale/);
  assert.match(css, /animation: pageEntry 120ms ease-out/);
});
test("both previews share completion-based exits, keyboard close and reduced-motion handling", () => {
  for (const file of ["./account-preview-drawer.tsx", "../contacts/components/contact-preview.tsx"]) {
    const source = read(file);
    assert.match(source, /useDrawerTransition/);
    assert.match(source, /onAnimationEnd=\{transition\.onAnimationEnd\}/);
    assert.match(source, /event\.key === "Escape"/);
  }
  const transition = read("../hooks/use-drawer-transition.ts");
  assert.match(transition, /prefers-reduced-motion: reduce/);
  assert.doesNotMatch(transition, /setTimeout/);
});
test("native disclosures animate intrinsic height and respect reduced motion without clipping to a fixed maximum", () => {
  assert.match(css, /@supports \(interpolate-size: allow-keywords\)/);
  assert.match(css, /details\[open\]::details-content \{ block-size: auto/);
  assert.match(css, /content-visibility 180ms allow-discrete/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /transition: none !important/);
  assert.doesNotMatch(css, /max-height:|transition: all/);
});
test("artifact content stays mounted until the closing transition finishes", () => {
  const screen = read("./account-library-screens.tsx");
  assert.match(screen, /onOpenChangeComplete=\{\(open\) => \{ if \(!open\) controller\.clearClosedArtifact\(\)/);
  assert.match(screen, /open=\{controller\.artifactOpen\}/);
  assert.match(read("../hooks/use-account-artifacts-controller.ts"), /closeArtifact: \(\) => setArtifactOpen\(false\)/);
});
