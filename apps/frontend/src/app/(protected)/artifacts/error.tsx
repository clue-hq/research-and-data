"use client";
import { Button } from "@/components/ui/button";
import { ApplicationShell } from "@/components/shell/application-shell";

/**
 * The library is one server-side read, so a failed read lands here rather than
 * as an in-screen warning. "Try again" is `unstable_retry` — the Next 16 prop
 * that re-fetches the segment (`node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/error.md`);
 * `reset` only re-renders the same failed contents, which would leave the
 * operator pressing a button that cannot recover.
 */
export default function Error({ unstable_retry }: { unstable_retry: () => void }) {
  return (
    <ApplicationShell activeHref="/artifacts">
      <main
        role="alert"
        className="flex h-full flex-col items-center justify-center gap-3 p-8"
      >
        <h1 className="text-lg">Artifacts couldn’t be loaded</h1>
        <p>Check your connection and try again.</p>
        <Button size="md" variant="secondary" onClick={() => unstable_retry()}>
          Try again
        </Button>
      </main>
    </ApplicationShell>
  );
}
