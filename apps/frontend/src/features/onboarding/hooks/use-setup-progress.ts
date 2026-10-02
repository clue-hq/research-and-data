"use client";

import { useEffect, useRef, useState } from "react";
import { SetupApiError, type SetupStatus } from "../data/setup";
import {
  httpSetupProgressSource,
  type SetupProgressSource,
} from "../data/setup-progress.repository";
import {
  isStalled,
  shouldStopSetupPolling,
  stallAdvance,
} from "../model/setup-stall";

const POLL_INTERVAL_MS = 1500;
/** Consecutive `none` reads tolerated after a successful start before surfacing (60s —
 * the fast lane's enclosing transaction can legitimately hide progress for a while; the
 * copy is "taking longer than expected", never an assertion that it hasn't started). */
const MAX_PENDING_POLLS = 40;
/** Consecutive transport failures tolerated before surfacing a connectivity message. */
const MAX_POLL_ERRORS = 5;

export type SetupTerminalKind =
  | "failed"
  | "unavailable"
  | "session"
  | "stalled"
  | null;

export interface SetupProgress {
  status: SetupStatus | null;
  failure: string | null;
  /** Which terminal family the failure belongs to — decides the recovery controls. */
  terminal: SetupTerminalKind;
}

/**
 * Owns the setting-up lifecycle: starts the (replay-safe) onboarding run for the profile's
 * company website, polls durable lane truth at 1.5s, and releases the user into the app when
 * the fast steps complete. Start failures and poll findings are SEPARATE channels — a poll tick
 * can never wipe a start failure it knows nothing about (review FE-B1) — and every terminal
 * state is surfaced with real recovery controls (review FE-B2). Polling stops on true backend terminals
 * and after release; a local stall fallback keeps observing durable truth so later readiness can
 * still release automatically. `location.replace` avoids the back-button trap (review FE-N6).
 *
 * Two independent budgets bound the wait, because neither covers the other: `MAX_PENDING_POLLS`
 * bounds consecutive `none` reads (nothing was ever requested), and the pure `stallAdvance`
 * bounds an in-flight run that reports nothing new — once the durable input row exists the read
 * surface never serves `none` again, so a dead backend driver would otherwise spin in `starting`
 * forever. Both end in the same recoverable terminal.
 *
 * Where the frames come from is the `source`'s business, not this hook's (slice 3): the live BFF
 * transport is the default, and a scripted local stream satisfies the same contract.
 */
export function useSetupProgress(
  { companyWebsite }: { companyWebsite: string },
  source: SetupProgressSource = httpSetupProgressSource,
): SetupProgress {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [terminal, setTerminal] = useState<SetupTerminalKind>(null);
  // Refs, not effect-locals: they survive StrictMode's double-invocation so a start failure
  // from the first run is re-applied by the second run's poll loop (review FE-N4).
  const startFailure = useRef<string | null>(null);
  const pendingPolls = useRef(0);
  // The second bound (see `model/setup-stall`): `none` is unreachable once the durable input row
  // exists, so a dead driver would otherwise spin in `starting` forever.
  const stallPolls = useRef(0);
  const lastSeen = useRef<SetupStatus | null>(null);
  const pollErrors = useRef(0);
  const released = useRef(false);
  const startedOnce = useRef(false);
  const stopped = useRef(false);
  // The transport is fixed for the hook's lifetime, exactly as the effect's empty deps say: a
  // caller handing a fresh source object to a re-render must not restart the run (that would
  // re-enter start and reset the pending/error counters mid-flight).
  const sourceRef = useRef(source);
  // Same reason: the company the run is started for is fixed for the screen's life. Capturing it
  // keeps the effect's empty deps honest — a re-render with a new string must not restart a run.
  const websiteRef = useRef(companyWebsite);

  useEffect(() => {
    let interval: number | null = null;

    function surface(message: string | null, kind: SetupTerminalKind) {
      setFailure(message);
      setTerminal(kind);
      if (shouldStopSetupPolling(kind)) {
        stopped.current = true;
        if (interval !== null) window.clearInterval(interval);
      }
    }

    async function ensureStarted() {
      if (startedOnce.current) return;
      startedOnce.current = true;
      try {
        await sourceRef.current.start({ companyWebsite: websiteRef.current });
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
        current = await sourceRef.current.read();
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
      stallPolls.current = stallAdvance(lastSeen.current, current, stallPolls.current);
      lastSeen.current = current;
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
          surface("Setup is taking longer than expected to start. You can retry.", "stalled");
        }
        return;
      }
      pendingPolls.current = 0;
      if (isStalled(stallPolls.current)) {
        // An in-flight run that has reported nothing new for the whole budget: the driver is
        // most likely gone (refusal / process restart / every iteration raising). Same
        // recoverable terminal as the `none` budget, so the user gets Try again + Continue
        // anyway instead of an eternal spinner.
        surface(
          "Setup is taking longer than expected. You can try again, or continue into your "
            + "workspace.",
          "stalled",
        );
        return;
      }
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
