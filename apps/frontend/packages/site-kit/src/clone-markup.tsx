import { useMemo, type Ref } from "react";
import type { Clone } from "./clone";

/** A cloned section's scoped CSS and markup. React 19 re-sets `innerHTML` whenever the
 * `dangerouslySetInnerHTML` object is a new one, even for the same string, which rebuilds the
 * clone's DOM: its images reload and lose their size (the page reflows), and whatever was marked on
 * its elements (CloneEditor's editable slots) is lost. So these objects change only when their
 * strings do, and re-rendering an unchanged clone touches nothing. */
export function CloneMarkup({
  clone,
  html,
  ref,
  inlineCss = true,
}: {
  clone: Clone;
  html: string;
  ref?: Ref<HTMLDivElement>;
  /** false on a live page, where the clones' CSS is one stylesheet outside the React tree
   * (render-core), so a redraw in the browser can never lose it. */
  inlineCss?: boolean;
}) {
  const css = useMemo(() => ({ __html: clone.css }), [clone.css]);
  const markup = useMemo(() => ({ __html: html }), [html]);
  return (
    <>
      {inlineCss ? <style dangerouslySetInnerHTML={css} /> : null}
      <div
        ref={ref}
        className={`lumen-fragment ${clone.wrapper_class}`}
        data-lumen-fragment="true"
        data-fragment-id={clone.id}
        dangerouslySetInnerHTML={markup}
      />
    </>
  );
}
