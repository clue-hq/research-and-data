import { useEffect, useRef } from "react";

const BOTTOM_THRESHOLD_PX = 40;

/**
 * Keep the transcript pinned to the bottom while the user is at the bottom.
 *
 * `revision` is any monotonically-changing signal that means "the transcript
 * grew" — the streamed cursor, or the message count. It replaces the old
 * `(generationProgress, phase)` pair, which tied scrolling to the manufactured
 * phase enum: with that gone, scrolling follows content, and an independent
 * reasoning or tool disclosure opening below the fold no longer yanks the view,
 * because the pin state is read from the user's own scroll position first.
 */
export function useTranscriptAutoScroll({
  activeMessageRevision,
  revision,
}: {
  activeMessageRevision: string | null;
  revision: number;
}) {
  const transcriptScrollRef = useRef<HTMLDivElement>(null);
  const pinnedToBottomRef = useRef(true);
  const previousActiveMessageRef = useRef(activeMessageRevision);

  useEffect(() => {
    const transcript = transcriptScrollRef.current;
    if (!transcript) return;

    const updatePinnedState = () => {
      const distanceFromBottom =
        transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight;
      pinnedToBottomRef.current = distanceFromBottom <= BOTTOM_THRESHOLD_PX;
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
      transcript
        .querySelector<HTMLElement>('[data-active-message="true"]')
        ?.scrollIntoView({
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
            ? "auto"
            : "smooth",
          block: "start",
        });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeMessageRevision]);

  return { transcriptScrollRef };
}
