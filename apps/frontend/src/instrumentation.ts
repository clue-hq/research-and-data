import { siteEditorStartupProblem } from "@/features/site-editor/server/startup-check";

/** Runs once when a Next.js server starts (Next's instrumentation hook). */
export function register(): void {
  const problem = siteEditorStartupProblem(process.env);
  if (problem) console.error(`[clue] ${problem}`);
}
