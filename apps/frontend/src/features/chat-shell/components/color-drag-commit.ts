/**
 * What the Custom tab's colour square or hue slider saves when a gesture ends.
 *
 * While the pointer moves, only the picker's own swatch follows it; the document is
 * written once, at the end, with the colour the gesture ended on — and not at all when
 * the gesture never moved or came back to the colour already saved.
 */
export function colorToCommitOnRelease(saved: string, pending: string | null): string | null {
  if (pending === null || pending.toUpperCase() === saved.toUpperCase()) return null;
  return pending;
}
