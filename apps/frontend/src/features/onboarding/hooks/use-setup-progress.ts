"use client";

import { useEffect, useRef, useState } from "react";
import {
  SetupApiError,
  readSetupStatus,
  startWorkspaceSetup,
  type SetupStatus,
} from "../data/setup";

const POLL_INTERVAL_MS = 1500;
/** Polls tolerated in "none" (recon row not visible yet) before we surface a start failure. */
const MAX_PENDING_POLLS = 20;

/**
 * Owns the slice-2 setting-up lifecycle: starts the (replay-safe) workspace setup, polls the
 * durable lane truth at 1.5s, and releases the user into the app when the fast lane completes.
 * Every state transition maps 1:1 to a durable recon-lane row — no timers advance anything.
 */
export function useSetupProgress(): {
  status: SetupStatus | null;
  failure: string | null;
} {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const pendingPolls = useRef(0);
  const released = useRef(false);
  const startedOnce = useRef(false);

  useEffect(() => {
    let cancelled = false;

    async function ensureStarted() {
      if (startedOnce.current) return;
      startedOnce.current = true;
      try {
        await startWorkspaceSetup();
      } catch (caught) {
        if (!cancelled) {
          setFailure(
            caught instanceof SetupApiError && caught.status === 409
              ? "Workspace setup isn't available for this account."
              : "We couldn't start your workspace setup. Please retry.",
          );
        }
      }
    }

    async function poll() {
      try {
        const current = await readSetupStatus();
        if (cancelled) return;
        setStatus(current);
        if (current.status === "none") {
          pendingPolls.current += 1;
          if (pendingPolls.current > MAX_PENDING_POLLS) {
            setFailure("Setup hasn't started. Please retry.");
          }
          return;
        }
        pendingPolls.current = 0;
        if (current.status === "failed") {
          setFailure(
            "Company research hit a problem. You can retry, or continue — we'll pick it up later.",
          );
          return;
        }
        setFailure(null);
        if (current.status === "complete" && !released.current) {
          released.current = true;
          window.location.assign("/session/establish");
        }
      } catch {
        // Transient poll failures are retried on the next tick; the durable rows are truth.
      }
    }

    void ensureStarted();
    void poll();
    const interval = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  return { status, failure };
}
