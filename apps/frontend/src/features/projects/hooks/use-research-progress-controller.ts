"use client";

import { useEffect, useState } from "react";
import { ResearchProgressResponseSchema, type ResearchProgress } from "../model/research-progress";
import { researchProgressHeadline, researchProgressLine } from "../model/research-progress-line";

/**
 * The pinned research card's state (spec 2026-09-12 §4–§5): reads on mount, re-reads every
 * `pollMs` while the read returns a card, rotates the status line every `rotateMs`, and stops
 * when the read returns `null` (the backend's own linger window decides that). `prime` bumps
 * once from outside (a completed launch tool part) so the card appears within a tick.
 */
export function useResearchProgressController(
  projectId: string,
  {
    pollMs = 5000,
    rotateMs = 4000,
    prime = 0,
  }: { pollMs?: number; rotateMs?: number; prime?: number } = {},
): { card: ResearchProgress | null; line: string; headline: string; tick: number } {
  const [card, setCard] = useState<ResearchProgress | null>(null);
  const [tick, setTick] = useState(0);
  // Bumped on every read that lands (a card or `null`): the Target accounts tab refetches its
  // rows on it, so "Researched" and the researched fields appear without a page reload.
  const [reads, setReads] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // Starts true so a FAILED first read keeps polling; only a read that lands and returns
    // `null` stops the poll, until `prime` or `projectId` re-runs the effect.
    let live = true;
    async function read() {
      try {
        const response = await fetch(
          `/api/projects/${encodeURIComponent(projectId)}/research-progress`,
          { cache: "no-store" },
        );
        if (!response.ok) return;
        const next = ResearchProgressResponseSchema.parse(await response.json()).data;
        if (cancelled) return;
        live = next !== null;
        setCard(next);
        setReads((current) => current + 1);
      } catch {
        // Keep the last card; the next tick tries again.
      }
    }
    void read();
    const poll = window.setInterval(() => {
      if (live) void read();
    }, pollMs);
    return () => {
      cancelled = true;
      window.clearInterval(poll);
    };
  }, [pollMs, prime, projectId]);

  // The rotation timer exists only while a card is on screen. Gated on the BOOLEAN, not on
  // `card` itself, so a poll that returns the same-shaped card does not restart the 4 s.
  const showing = card !== null;
  useEffect(() => {
    if (!showing) return;
    const rotate = window.setInterval(() => setTick((current) => current + 1), rotateMs);
    return () => window.clearInterval(rotate);
  }, [rotateMs, showing]);

  return {
    card,
    line: card ? researchProgressLine(card, tick) : "",
    headline: card ? researchProgressHeadline(card) : "",
    tick: reads,
  };
}
