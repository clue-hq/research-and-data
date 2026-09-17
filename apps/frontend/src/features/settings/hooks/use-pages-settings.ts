"use client";

import { useCallback, useEffect, useState } from "react";

import { useConfirmation } from "@/components/ui/confirmation-card";
import { ClueApiError } from "@/features/accounts/data/clue-api-error";

import {
  changeSystemLabel,
  checkCustomHostname,
  connectCustomHostname,
  removeCustomHostname,
  updatePagesSettings,
  uploadPagesImage,
  type PagesSettingsPatch,
} from "../data/pages.actions";
import {
  connectionView,
  REFUSAL_MESSAGES,
  type PagesSettingsRead,
} from "../model/pages";

/** Spec §8.2 state 2: the card re-checks itself while the hostname is still provisioning. */
const POLL_INTERVAL_MS = 5000;

function messageFor(error: unknown): string {
  return error instanceof ClueApiError ? error.message : "Something went wrong.";
}

/**
 * `REFUSAL_MESSAGES` carries copy for the custom-hostname refusal codes only.
 * Every other code (including the `label_*` family) falls through to the
 * server's own message rather than being guessed at here.
 */
function refusalFor(error: unknown): string {
  if (!(error instanceof ClueApiError)) return "Something went wrong.";
  return REFUSAL_MESSAGES[error.code] ?? error.message;
}

export interface PagesSettingsController {
  state: PagesSettingsRead;
  /** Inline refusal under the custom-hostname input; `null` while the input is clean. */
  refusal: string | null;
  busy: boolean;
  /** Rejects on failure so {@link SettingsAutosaveInput} can restore the saved value. */
  save: (patch: PagesSettingsPatch) => Promise<void>;
  upload: (kind: "favicon" | "social-preview", file: File) => Promise<void>;
  /** `true` when the label changed; the editor stays open on a refusal. */
  changeLabel: (label: string) => Promise<boolean>;
  connect: (hostname: string) => Promise<void>;
  check: () => Promise<void>;
  remove: () => Promise<void>;
}

export function usePagesSettings(initial: PagesSettingsRead): PagesSettingsController {
  const confirm = useConfirmation();
  const [state, setState] = useState(initial);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /** Run one action, adopt its response as the new truth, and report the outcome. */
  const run = useCallback(
    async (action: () => Promise<PagesSettingsRead>) => {
      setBusy(true);
      try {
        setState(await action());
        confirm("Pages updated");
      } catch (error) {
        confirm(messageFor(error), "error");
        throw error;
      } finally {
        setBusy(false);
      }
    },
    [confirm],
  );

  const save = useCallback(
    (patch: PagesSettingsPatch) => run(() => updatePagesSettings(patch)),
    [run],
  );

  const upload = useCallback(
    async (kind: "favicon" | "social-preview", file: File) => {
      await run(() => uploadPagesImage(kind, file)).catch(() => undefined);
    },
    [run],
  );

  const changeLabel = useCallback(
    async (label: string) => {
      try {
        await run(() => changeSystemLabel(label));
        return true;
      } catch {
        return false;
      }
    },
    [run],
  );

  const connect = useCallback(
    async (hostname: string) => {
      setRefusal(null);
      try {
        await run(() => connectCustomHostname(hostname));
      } catch (error) {
        setRefusal(refusalFor(error));
      }
    },
    [run],
  );

  const check = useCallback(async () => {
    await run(checkCustomHostname).catch(() => undefined);
  }, [run]);

  /**
   * Removal answers `204`, so the fresh truth comes from the check that follows —
   * which is also what retries a removal the provider left stuck in `disconnecting`.
   */
  const remove = useCallback(async () => {
    try {
      await run(async () => {
        await removeCustomHostname();
        return checkCustomHostname();
      });
    } catch (error) {
      // The backend marks the row `disconnecting` BEFORE it calls the provider, so a provider
      // failure leaves a row this screen must show as removing (and poll to completion).
      if (error instanceof ClueApiError && error.status === 502) {
        setState((current) =>
          current.customHostname
            ? { ...current, customHostname: { ...current.customHostname, status: "disconnecting" } }
            : current,
        );
      }
    }
  }, [run]);

  const view = connectionView(state.customHostname);

  useEffect(() => {
    if (view !== "connecting") return;
    let inFlight = false;
    const timer = setInterval(() => {
      // A slow check must not stack behind itself: skip the tick instead.
      if (inFlight) return;
      inFlight = true;
      // The poll is background work, so it neither toasts nor reports failure —
      // an unreachable provider leaves the last known state on screen.
      void checkCustomHostname()
        .then(setState)
        .catch(() => undefined)
        .finally(() => {
          inFlight = false;
        });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [view]);

  return { state, refusal, busy, save, upload, changeLabel, connect, check, remove };
}
