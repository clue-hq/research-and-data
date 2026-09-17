import { useEffect, useLayoutEffect, useRef } from "react";

const BOTTOM_THRESHOLD_PX = 40;
const TOP_THRESHOLD_PX = 48;

/** The two DOM reads the scroll arithmetic needs — narrow so the helpers stay testable without a DOM. */
interface Measurable {
  getBoundingClientRect(): { top: number };
}
interface ScrollContainer extends Measurable {
  scrollTop: number;
  scrollTo(options: { top: number; behavior: ScrollBehavior }): void;
}

/** Where an element sits inside a scroll container, independent of offset parents. */
function offsetWithin(element: Measurable, container: ScrollContainer): number {
  return (
    element.getBoundingClientRect().top -
    container.getBoundingClientRect().top +
    container.scrollTop
  );
}

/**
 * Bring `element` to the top of `container` by scrolling the CONTAINER, never the page.
 *
 * `element.scrollIntoView` walks every ancestor and scrolls whichever it needs to satisfy the
 * request — and an ancestor with `overflow: hidden` is still scrollable programmatically. On
 * the live chat (2026-09-16) the transcript could not put a fresh message at its top on its own,
 * so the browser scrolled the chat pane itself: the header slid out of view and the composer
 * rode up with every message until a refresh. Computing the target inside the container and
 * calling its own `scrollTo` makes that impossible whatever the surrounding layout does.
 */
export function scrollMessageToTop(
  container: ScrollContainer,
  element: Measurable,
  { paddingTop, behavior }: { paddingTop: number; behavior: ScrollBehavior },
): void {
  container.scrollTo({
    top: Math.max(0, offsetWithin(element, container) - paddingTop),
    behavior,
  });
}

/**
 * Keep the transcript pinned to the bottom while the user is at the bottom.
 *
 * `revision` is any monotonically-changing signal that means "the transcript
 * grew" — the streamed cursor, or the message count. It replaces the old
 * `(generationProgress, phase)` pair, which tied scrolling to the manufactured
 * phase enum: with that gone, scrolling follows content, and an independent
 * reasoning or tool disclosure opening below the fold no longer yanks the view,
 * because the pin state is read from the user's own scroll position first.
 *
 * **Scrollback (Slice C C5).** With the durable read newest-first, older
 * history loads on demand: reaching the top of the list calls `onLoadOlder`
 * once per fetch, and when the prepended page lands the view is re-anchored to
 * the message the user was looking at — same reading position, no jump, no new
 * UI. The anchor is the oldest loaded message's own element (via its
 * `data-message-id`), which makes the restoration immune to content growing at
 * the bottom while the fetch is in flight.
 */
export function useTranscriptAutoScroll({
  activeMessageRevision,
  canLoadOlder = false,
  onLoadOlder,
  revision,
}: {
  activeMessageRevision: string | null;
  /** True while an older transcript page exists to fetch. */
  canLoadOlder?: boolean;
  /** Fetch-and-prepend the preceding page; must be idempotent while in flight. */
  onLoadOlder?: () => void;
  revision: number;
}) {
  const transcriptScrollRef = useRef<HTMLDivElement>(null);
  const pinnedToBottomRef = useRef(true);
  const previousActiveMessageRef = useRef(activeMessageRevision);
  const scrollback = useRef({ canLoadOlder, onLoadOlder });
  useLayoutEffect(() => {
    scrollback.current = { canLoadOlder, onLoadOlder };
  });
  const pendingPrepend = useRef<{
    anchorId: string;
    anchorOffset: number;
    scrollTop: number;
  } | null>(null);

  useEffect(() => {
    const transcript = transcriptScrollRef.current;
    if (!transcript) return;

    const maybeLoadOlder = () => {
      const { canLoadOlder: enabled, onLoadOlder: load } = scrollback.current;
      if (!enabled || !load || pendingPrepend.current !== null) return;
      if (transcript.scrollTop > TOP_THRESHOLD_PX) return;
      const anchor = transcript.querySelector<HTMLElement>("[data-message-id]");
      if (!anchor) return;
      pendingPrepend.current = {
        anchorId: anchor.dataset.messageId ?? "",
        anchorOffset: offsetWithin(anchor, transcript),
        scrollTop: transcript.scrollTop,
      };
      load();
    };
    const updatePinnedState = () => {
      const distanceFromBottom =
        transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight;
      pinnedToBottomRef.current = distanceFromBottom <= BOTTOM_THRESHOLD_PX;
      maybeLoadOlder();
    };
    const scrollToBottom = () => {
      if (!pinnedToBottomRef.current) return;
      transcript.scrollTo({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "auto"
          : "smooth",
        top: transcript.scrollHeight,
      });
    };
    const observer = new ResizeObserver(scrollToBottom);
    observer.observe(transcript);
    if (transcript.firstElementChild) observer.observe(transcript.firstElementChild);
    transcript.addEventListener("scroll", updatePinnedState, { passive: true });
    scrollToBottom();

    return () => {
      observer.disconnect();
      transcript.removeEventListener("scroll", updatePinnedState);
    };
  }, []);

  // Restore the reading position once a prepended page has actually landed.
  // Runs every commit: until the anchor moves the effect is a no-op that keeps
  // waiting, so a stream update racing the fetch cannot consume the snapshot.
  useLayoutEffect(() => {
    const transcript = transcriptScrollRef.current;
    const saved = pendingPrepend.current;
    if (!transcript || !saved) return;
    const anchor = transcript.querySelector<HTMLElement>(
      `[data-message-id="${CSS.escape(saved.anchorId)}"]`,
    );
    if (!anchor) {
      pendingPrepend.current = null;
      return;
    }
    const delta = offsetWithin(anchor, transcript) - saved.anchorOffset;
    if (delta === 0) return;
    pendingPrepend.current = null;
    transcript.scrollTop = saved.scrollTop + delta;
  });

  useEffect(() => {
    const transcript = transcriptScrollRef.current;
    if (!transcript || !pinnedToBottomRef.current) return;
    const frame = window.requestAnimationFrame(() => {
      transcript.scrollTo({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "auto"
          : "smooth",
        top: transcript.scrollHeight,
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [revision]);

  useEffect(() => {
    if (
      activeMessageRevision === null ||
      activeMessageRevision === previousActiveMessageRef.current
    ) {
      return;
    }
    previousActiveMessageRef.current = activeMessageRevision;
    const transcript = transcriptScrollRef.current;
    if (!transcript) return;

    // A newly submitted user message is the reading anchor for its response.
    // Stop bottom-pinning until the person scrolls back down; otherwise each
    // streamed delta moves the message upward and eventually under the sticky
    // project/thread headers.
    pinnedToBottomRef.current = false;
    const frame = window.requestAnimationFrame(() => {
      const message = transcript.querySelector<HTMLElement>('[data-active-message="true"]');
      if (!message) return;
      // The transcript's own scroll-padding (`scroll-padding-block`) is what `scrollIntoView`
      // would have honoured; read it so the anchor lands where the stylesheet says.
      const paddingTop = Number.parseFloat(getComputedStyle(transcript).scrollPaddingTop) || 0;
      scrollMessageToTop(transcript, message, {
        paddingTop,
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "auto"
          : "smooth",
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeMessageRevision]);

  return { transcriptScrollRef };
}
