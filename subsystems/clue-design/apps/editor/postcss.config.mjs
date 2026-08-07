/** PostCSS — Tailwind 4 pipeline for the editor.
 *
 * Tailwind is present as the utility/theme substrate for shadcn/ui + (later)
 * AI Elements on the conversation surfaces. The editor's hand-rolled global
 * CSS (src/app/styles.css) and the CanvasKit stage own the shell today; we do
 * NOT ship Tailwind's Preflight reset here — see src/app/tailwind.css for the
 * rationale. This config only wires the `@tailwindcss/postcss` plugin so the
 * `@import "tailwindcss/*"` layers in tailwind.css compile.
 */
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;
