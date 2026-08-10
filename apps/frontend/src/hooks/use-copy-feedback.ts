import { useCallback, useEffect, useRef, useState } from "react";

export function useCopyFeedback({
  copiedLabel,
  idleLabel,
  resetAfter = 1500,
}: {
  copiedLabel: string;
  idleLabel: string;
  resetAfter?: number;
}) {
  const [copied, setCopied] = useState(false);
  const timeout = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timeout.current !== null) window.clearTimeout(timeout.current);
    },
    [],
  );

  const copyCurrentUrl = useCallback(async () => {
    await navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    timeout.current = window.setTimeout(() => setCopied(false), resetAfter);
  }, [resetAfter]);

  return {
    copied,
    copyCurrentUrl,
    label: copied ? copiedLabel : idleLabel,
  };
}
