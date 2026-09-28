"use client";

import { useCallback, useEffect, useState } from "react";

import { useConfirmation } from "@/components/ui/confirmation-card";
import { ClueApiError } from "@/features/accounts/data/clue-api-error";

import { useAutosaveField } from "./use-autosave-field";

import {
  changeSystemLabel,
  checkCustomHostname,
  connectCustomHostname,
  removeCustomHostname,
  updatePagesSettings,
  uploadPagesImage,
} from "../data/pages.actions";
import {
  connectionView,
  REFUSAL_MESSAGES,
  type PagesSettingsRead,
} from "../model/pages";

/** Spec §8.2 state 2: the card re-checks itself while the hostname is still provisioning. */
const POLL_INTERVAL_MS = 5000;

/**
 * `REFUSAL_MESSAGES` carries copy for the custom-hostname refusal codes and the
 * `label_locked` / `label_taken` / `label_invalid` label refusals. Every other
 * code falls through to the server's own message rather than being guessed at here.
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
  /** The three text defaults, each an autosave field bound on blur/Enter. */
  fallbackUrl: ReturnType<typeof useAutosaveField>;
  pageTitle: ReturnType<typeof useAutosaveField>;
  pageDescription: ReturnType<typeof useAutosaveField>;
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
        confirm(refusalFor(error), true);
        throw error;
      } finally {
        setBusy(false);
      }
    },
    [confirm],
  );

  // Each default saves on its own through the settings slice's autosave field,
  // which owns the confirmation card and restores the saved value on a refusal.
  // An emptied field clears the default (`null`), matching the backend's shape.
  const fallbackUrl = useAutosaveField(
    initial.settings.fallbackUrl ?? "",
    async (value) => {
      const next = await updatePagesSettings({ fallbackUrl: value || null });
      setState(next);
      return next.settings.fallbackUrl ?? "";
    },
    "Pages updated",
  );
  const pageTitle = useAutosaveField(
    initial.settings.pageTitle ?? "",
    async (value) => {
      const next = await updatePagesSettings({ pageTitle: value || null });
      setState(next);
      return next.settings.pageTitle ?? "";
    },
    "Pages updated",
  );
  const pageDescription = useAutosaveField(
    initial.settings.pageDescription ?? "",
    async (value) => {
      const next = await updatePagesSettings({ pageDescription: value || null });
      setState(next);
      return next.settings.pageDescription ?? "";
    },
    "Pages updated",
    { multiline: true },
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

  return {
    state,
    refusal,
    busy,
    fallbackUrl,
    pageTitle,
    pageDescription,
    upload,
    changeLabel,
    connect,
    check,
    remove,
  };
}
