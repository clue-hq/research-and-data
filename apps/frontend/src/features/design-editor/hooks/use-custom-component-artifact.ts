"use client";

import { useEffect, useState } from "react";
import { designBffConfig } from "../data/design-bff";
import {
  fetchCustomComponentArtifact,
  type CustomComponentArtifact,
} from "../engine/webDocuments";

/**
 * W4.7 (contract item 34): the pinned artifact behind a selected custom
 * component — the manifest whose `props_schema` the inspector's props form
 * renders from.
 *
 * `GET /web/accounts/{accountId}/custom-component-artifacts/{artifactId}`
 * through the authenticated BFF, one fetch per id pair. Either id null (no
 * account-bound document, or a node carrying no pin) → `idle`, no fetch.
 *
 * Ledgered ruling (2026-08-18): the form is item 34's whole scope, so `loading`
 * and `error` exist only to say "there is no form yet" — the caller renders NO
 * loading shell and NO error chrome, and the §5 layout fallback simply stands
 * alone. That is also why a failure carries a message the caller currently
 * ignores: it is kept so the state is honest, not so it can be displayed.
 *
 * Lives in hooks/ (not the presentation component) per the repo seam rule:
 * presentation receives typed props and never imports data/ or the engine.
 * Results are STAMPED with the id pair they were fetched for and derived
 * against the current pair — a switched selection never serves the previous
 * component's manifest, and nothing is set synchronously inside the effect
 * (`react-hooks/set-state-in-effect`). Same idiom as `useWebTheme` /
 * `useWebArtifactSelection`.
 */
export type CustomComponentArtifactState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; artifact: CustomComponentArtifact }
  | { status: "error"; message: string };

/** One key for the (account, artifact) pair. NUL-joined so no pair of ids can
 * collide by concatenation. */
function artifactKey(
  accountId: string | null,
  artifactId: string | null,
): string | null {
  return accountId && artifactId ? `${accountId}\u0000${artifactId}` : null;
}

export function useCustomComponentArtifact(
  accountId: string | null,
  artifactId: string | null,
): CustomComponentArtifactState {
  const key = artifactKey(accountId, artifactId);
  const [settled, setSettled] = useState<{
    forKey: string;
    result:
      | { ok: true; artifact: CustomComponentArtifact }
      | { ok: false; message: string };
  } | null>(null);

  useEffect(() => {
    if (!accountId || !artifactId) return;
    const pending = artifactKey(accountId, artifactId);
    if (!pending) return;
    let cancelled = false;
    fetchCustomComponentArtifact(designBffConfig(), accountId, artifactId)
      .then((artifact) => {
        if (!cancelled) {
          setSettled({ forKey: pending, result: { ok: true, artifact } });
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setSettled({
          forKey: pending,
          result: {
            message:
              error instanceof Error
                ? error.message
                : "Custom-component artifact failed to load.",
            ok: false,
          },
        });
      });
    return () => {
      cancelled = true;
    };
  }, [accountId, artifactId]);

  if (!key) return { status: "idle" };
  if (settled?.forKey !== key) return { status: "loading" };
  return settled.result.ok
    ? { artifact: settled.result.artifact, status: "ready" }
    : { message: settled.result.message, status: "error" };
}
