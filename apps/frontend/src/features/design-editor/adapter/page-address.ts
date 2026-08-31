import type { LoadedWebDocument } from "../engine/webDocuments";

/**
 * The one node → page resolution every addressed write shares.
 *
 * A `WebOperation` carries the `page_id` its node lives on, and that page is
 * found by NODE MEMBERSHIP — never by taking the first page. An op addressed to
 * the wrong page is a server rejection at best and a cross-page write at worst,
 * so a node that belongs to no loaded page yields `null` (no operation) rather
 * than a guessed address.
 *
 * Extracted at W4.7 from `rich-text-commit.ts`, which held the first copy of
 * this lookup: the custom-component props commit needs the identical
 * resolution, and two copies of an addressing rule is exactly the drift the
 * repo's DRY discipline forbids. (`use-inspector-writes.ts` performs the same
 * find inline against its own selection ref; folding that one in touches a file
 * this lane does not own, so it stays where it is.)
 */
export function pageIdForNode(
  document: LoadedWebDocument | null,
  nodeId: string,
): string | null {
  const page = document?.webDoc?.pages?.find((candidate) =>
    Boolean(candidate.nodes?.[nodeId]),
  );
  return page ? page.id : null;
}
