import type { ResearchItem } from "../model/research-display";

/** A citation on its own after a Markdown heading belongs to that heading. */
export function presentResearchItem(item: ResearchItem) {
  const firstSentence = item.body[0];
  const firstSegment = firstSentence?.segments?.[0];
  if (
    item.inlineLead ||
    !firstSegment?.claimIds.length ||
    !/^[\s.,;:]*$/.test(firstSegment.text)
  ) {
    return { headingClaimIds: [] as string[], body: item.body };
  }

  const remainingSegments = firstSentence.segments!.slice(1);
  const remainingBody = remainingSegments.length
    ? [{
        ...firstSentence,
        text: remainingSegments.map((segment) => segment.text).join(""),
        claimIds: remainingSegments.flatMap((segment) => segment.claimIds),
        segments: remainingSegments,
      }, ...item.body.slice(1)]
    : item.body.slice(1);

  return { headingClaimIds: firstSegment.claimIds, body: remainingBody };
}
