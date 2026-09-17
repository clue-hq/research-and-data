"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Check, X } from "lucide-react";

/**
 * The settings confirmation card (settings spec §6.3): one transient line that
 * acknowledges an autosave or reports why it refused.
 *
 * Token note: `--clue-ds-radius-md`, `--clue-ds-color-surface-inverse`,
 * `--clue-ds-color-text-inverse`, `--clue-ds-color-success` and
 * `--clue-ds-color-danger` do not exist in
 * `packages/design-system/generated/tokens.css`; the closest existing tokens are
 * used instead (see the task-11 report for the substitution table).
 */
interface Confirmation {
  id: number;
  text: string;
  tone: "ok" | "error";
}

const ConfirmationContext = createContext<(text: string, tone?: "ok" | "error") => void>(() => {});

export function useConfirmation() {
  return useContext(ConfirmationContext);
}

export function ConfirmationCardProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<Confirmation | null>(null);
  const show = useCallback(
    (text: string, tone: "ok" | "error" = "ok") => setCurrent({ id: Date.now(), text, tone }),
    [],
  );
  useEffect(() => {
    if (!current) return;
    const timer = setTimeout(() => setCurrent(null), 4000);
    return () => clearTimeout(timer);
  }, [current]);
  const value = useMemo(() => show, [show]);
  return (
    <ConfirmationContext.Provider value={value}>
      {children}
      {current ? (
        <div
          role="status"
          className="fixed bottom-4 right-4 z-50 flex items-center gap-2 rounded-[var(--clue-ds-product-component-button-md-radius)] border-[0.5px] border-[var(--clue-ds-color-border-subtle)] bg-[var(--clue-ds-color-primitives-gray-900)] px-3 py-2 text-[var(--clue-ds-color-content-knockout)] shadow"
        >
          <Check
            size={14}
            aria-hidden="true"
            className={
              current.tone === "ok"
                ? "text-[var(--clue-ds-color-primitives-positive-400)]"
                : "text-[var(--clue-ds-color-primitives-critical-400)]"
            }
          />
          <span>{current.text}</span>
          <button aria-label="Dismiss" onClick={() => setCurrent(null)} type="button">
            <X size={14} />
          </button>
        </div>
      ) : null}
    </ConfirmationContext.Provider>
  );
}
