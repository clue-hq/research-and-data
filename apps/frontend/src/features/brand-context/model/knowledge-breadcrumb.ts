/**
 * The knowledge document breadcrumb, derived from route state.
 *
 * The brand-context page's document header used to render the literals
 * `Company / brand-kit.md` above every document — true of exactly one file that
 * this store does not serve, and a plain lie above `design/Design.md`. The
 * breadcrumb's job is to say where in the knowledge tree the reader is, and the
 * page already knows: the route carries `?section=knowledge&file=<path>` and the
 * selected document carries that same `path`.
 *
 * So the trail is DERIVED, never mapped. There is no table of file names to
 * pretty labels here, because a table is just the same hardcoded lie with more
 * rows — the day someone adds `audience/ICP.md` the table is wrong again.
 * Folder segments are humanized from their own path segment; the file segment
 * keeps its real name, because a file name (`Design.md`, `brand-kit.md`) is
 * already what a reader would call it.
 */

export type KnowledgeBreadcrumbKind = "folder" | "file";

export interface KnowledgeBreadcrumbSegment {
  readonly kind: KnowledgeBreadcrumbKind;
  readonly label: string;
}

/**
 * `design/Design.md` → `[Design, Design.md]`.
 *
 * Empty, blank and separator-only paths return an empty trail: with nothing to
 * say, the header says nothing rather than inventing a parent. A root-level
 * document gets one `file` segment and no folder — there is no parent to name.
 */
export function knowledgeBreadcrumb(path: string): KnowledgeBreadcrumbSegment[] {
  const segments = decodePath(path)
    .split("/")
    .map((segment) => segment.trim())
    .filter((segment) => segment.length > 0);

  if (segments.length === 0) return [];

  const file = segments[segments.length - 1];
  const folders = segments.slice(0, -1);

  return [
    ...folders.map(
      (folder): KnowledgeBreadcrumbSegment => ({
        kind: "folder",
        label: humanizeFolder(folder),
      }),
    ),
    { kind: "file", label: file },
  ];
}

/**
 * The path as a reader would see it. The route carries it percent-encoded
 * (`file=design%2FDesign.md`); a malformed escape is left alone rather than
 * throwing and blanking the header.
 */
function decodePath(path: string): string {
  try {
    return decodeURIComponent(path);
  } catch {
    return path;
  }
}

/**
 * `audience_research` → `Audience Research`; `design` → `Design`; `Proof` →
 * `Proof`. Separators become spaces and each word gets a capital first letter —
 * the rest of the word is left exactly as stored, so `ICP` stays `ICP`.
 */
function humanizeFolder(segment: string): string {
  return segment
    .replace(/[-_]+/g, " ")
    .split(" ")
    .filter((word) => word.length > 0)
    .map((word) => word.charAt(0).toLocaleUpperCase() + word.slice(1))
    .join(" ");
}
