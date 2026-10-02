import type { ResearchStatus } from "./account";

/**
 * The wording the backend serves as `researchStatusLabel`
 * (`platform/api/clue_api/frontend_read/v1_shared.py::RESEARCH_STATUS_LABELS`).
 *
 * This table exists ONLY so the fixtures can stand in for the backend. No
 * component may import it: a screen renders `researchStatusLabel ?? status`,
 * because the status vocabulary is the backend's (source map §6).
 */
export const FIXTURE_RESEARCH_STATUS_LABELS: Record<ResearchStatus, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  needs_review: "Needs review",
  completed: "Researched",
  suspended: "Paused",
};
