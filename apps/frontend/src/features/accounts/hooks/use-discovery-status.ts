"use client";

import { useEffect, useRef, useState } from "react";
import {
  DiscoveryRunStatusResponseSchema,
  discoveryRunLive,
  type DiscoveryRunStatus,
} from "../model/discovery-status";

/**
 * The project's discovery run, polled while it is live (spec 2026-09-12 §3).
 *
 * Reads on mount; while the run is live it re-reads every `pollMs` and bumps `tick` on each
 * read so the Target accounts tab refetches its rows. `prime` bumps once from outside (the
 * launch signal) so the first poll after a launch does not wait a whole interval. A failed
 * read keeps the last status and tries again on the next tick — including the very first read,
 * whose failure would otherwise leave the status unresolved and the run unknowable: the interval
 * keeps reading until one read lands, and only then does liveness decide. Polling stops on the
 * first terminal status.
 */
export function useDiscoveryStatus(
  projectId: string,
  { pollMs = 5000, prime = 0 }: { pollMs?: number; prime?: number } = {},
): { status: DiscoveryRunStatus | null; live: boolean; tick: number } {
  const [status, setStatus] = useState<DiscoveryRunStatus | null>(null);
  const [tick, setTick] = useState(0);
  const live = discoveryRunLive(status);
  // The interval reads liveness through a ref so a status change does not tear the timer down
  // and restart its 5 s. Written in a passive effect, not during render — this repo's
  // react-hooks lint forbids the render-time write (same adaptation as use-web-bridge-selection).
  const liveRef = useRef(live);
  useEffect(() => {
    liveRef.current = live;
  }, [live]);
  // Has any read ever landed? Until one has, `status` is null and `live` is false, so gating the
  // interval on liveness alone would let a single failed mount read (a 502 from the BFF, an
  // offline blip) kill the poll for the life of the mount.
  const settledRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    async function read() {
      try {
        const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/discovery`, {
          cache: "no-store",
        });
        if (!response.ok) return;
        const next = DiscoveryRunStatusResponseSchema.parse(await response.json()).data;
        if (cancelled) return;
        settledRef.current = true;
        setStatus(next);
        setTick((current) => current + 1);
      } catch {
        // Keep the last status; the next tick tries again.
      }
    }
    void read();
    const interval = window.setInterval(() => {
      if (liveRef.current || !settledRef.current) void read();
    }, pollMs);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [pollMs, prime, projectId]);

  return { status, live, tick };
}
