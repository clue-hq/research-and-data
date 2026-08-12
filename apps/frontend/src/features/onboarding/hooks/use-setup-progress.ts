"use client";

import { useEffect, useRef, useState } from "react";
import {
  SetupApiError,
  readSetupStatus,
  startWorkspaceSetup,
  type SetupStatus,
} from "../data/setup";

const POLL_INTERVAL_MS = 1500;
/** Consecutive `none` reads tolerated after a successful start before surfacing (60s —
 * the fast lane's enclosing transaction can legitimately hide progress for a while; the
 * copy is "taking longer than expected", never an assertion that it hasn't started). */
const MAX_PENDING_POLLS = 40;
/** Consecutive transport failures tolerated before surfacing a connectivity message. */
const MAX_POLL_ERRORS = 5;

export type SetupTerminalKind = "failed" | "unavailable" | "session" | null;

export interface SetupProgress {
  status: SetupStatus | null;
  failure: string | null;
  /** Which terminal family the failure belongs to — decides the recovery controls. */
  terminal: SetupTerminalKind;
}

/**
 * Owns the slice-2 setting-up lifecycle: starts the (replay-safe) workspace setup, polls
 * durable lane truth at 1.5s, and releases the user into the app when the fast lane
 * completes. Start failures and poll findings are SEPARATE channels — a poll tick can never
 * wipe a start failure it knows nothing about (review FE-B1) — and every terminal state is
 * surfaced with real recovery controls (review FE-B2). Polling stops on terminal states and
 * after release; `location.replace` avoids the back-button trap (review FE-N6).
 */
export function useSetupProgress(): SetupProgress {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [terminal, setTerminal] = useState<SetupTerminalKind>(null);
  // Refs, not effect-locals: they survive StrictMode's double-invocation so a start failure
  // from the first run is re-applied by the second run's poll loop (review FE-N4).
  const startFailure = useRef<string | null>(null);
  const pendingPolls = useRef(0);
  const pollErrors = useRef(0);
  const released = useRef(false);
  const startedOnce = useRef(false);
  const stopped = useRef(false);

  useEffect(() => {
    let interval: number | null = null;

    function surface(message: string | null, kind: SetupTerminalKind) {
      setFailure(message);
      setTerminal(kind);
      if (kind !== null && kind !== "session") {
        stopped.current = true;
        if (interval !== null) window.clearInterval(interval);
      }
    }

    async function ensureStarted() {
      if (startedOnce.current) return;
      startedOnce.current = true;
      try {
        await startWorkspaceSetup();
      } catch (caught) {
        startFailure.current =
          caught instanceof SetupApiError && caught.status === 409
            ? "Workspace setup isn't available for this account."
            : "We couldn't start your workspace setup. Please retry.";
      }
    }

    async function poll() {
      if (stopped.current || released.current) return;
      // A durably-recorded start failure always wins over whatever this tick sees.
      if (startFailure.current !== null) {
        surface(
          startFailure.current,
          startFailure.current.includes("isn't available") ? "unavailable" : "failed",
        );
        return;
      }
      let current: SetupStatus;
      try {
        current = await readSetupStatus();
      } catch (caught) {
        if (caught instanceof SetupApiError && (caught.status === 401 || caught.status === 403)) {
          surface("Your session has expired. Please sign in again.", "session");
          return;
        }
        pollErrors.current += 1;
        if (pollErrors.current >= MAX_POLL_ERRORS) {
          setFailure("We can't reach setup right now — retrying…");
          setTerminal(null);
        }
        return;
      }
      pollErrors.current = 0;
      setStatus((previous) =>
        previous !== null && JSON.stringify(previous) === JSON.stringify(current)
          ? previous
          : current,
      );
      if (current.status === "unavailable") {
        surface("Workspace setup isn't available for this account.", "unavailable");
        return;
      }
      if (current.status === "failed") {
        surface(
          "Company research hit a problem. You can try again, or continue into your workspace.",
          "failed",
        );
        return;
      }
      if (current.status === "none") {
        pendingPolls.current += 1;
        if (pendingPolls.current > MAX_PENDING_POLLS) {
          surface("Setup is taking longer than expected to start. You can retry.", "failed");
        }
        return;
      }
      pendingPolls.current = 0;
      setFailure(null);
      setTerminal(null);
      if (current.status === "complete" && !released.current) {
        released.current = true;
        window.location.replace("/session/establish");
      }
    }

    void ensureStarted();
    void poll();
    interval = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      if (interval !== null) window.clearInterval(interval);
    };
  }, []);

  return { status, failure, terminal };
}
