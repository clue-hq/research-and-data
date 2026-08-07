import { useEffect, useRef } from "react";
import type { ProjectPhase } from "../model/project-workspace";

const BOTTOM_THRESHOLD_PX = 40;

export function useTranscriptAutoScroll({
  generationProgress,
  phase,
}: {
  generationProgress: number;
  phase: ProjectPhase;
}) {
  const transcriptScrollRef = useRef<HTMLDivElement>(null);
  const pinnedToBottomRef = useRef(true);

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
  }, [generationProgress, phase]);

  return { transcriptScrollRef };
}
