"use client";
import { Button } from "@/components/ui/button";

/**
 * Settings is one server-side read, so a failed read lands here rather than as an
 * in-screen warning. "Try again" is `unstable_retry` — the Next 16 prop that
 * re-fetches the segment; `reset` only re-renders the same failed contents.
 *
 * No `ApplicationShell`: the settings screen owns its own sidebar.
 */
export default function Error({ unstable_retry }: { unstable_retry: () => void }) {
  return (
    <main
      role="alert"
      className="flex h-full flex-col items-center justify-center gap-3 p-8"
    >
      <h1 className="text-lg">Settings couldn’t be loaded</h1>
      <p>Check your connection and try again.</p>
      <Button size="md" variant="secondary" onClick={() => unstable_retry()}>
        Try again
      </Button>
    </main>
  );
}
