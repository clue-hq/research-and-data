/**
 * Local preview data for the setting-up flow, over the NEW onboarding lane (spec 2026-09-12).
 *
 * Fixtures are wire-shaped: every frame below is exactly what `GET /api/clue/onboarding/current`
 * reduces to, so the fixture source validates through the same `SetupStatusSchema` the HTTP
 * adapter does. A fixture that skipped validation would let the two drift, which is the failure
 * the repository seam exists to prevent.
 *
 * The script is a **state stream, not a lifecycle model**: the poll tick is transport, the frame
 * is the state. Nothing here advances because time passed — every state the checklist renders
 * comes from a frame, exactly as it does against a live backend.
 *
 * What it replays is the lane's own vocabulary, end to end:
 *
 * 1. `starting` — the run row exists and has not begun (queued); no step has reported, so the
 *    checklist shows its warm-up row and claims nothing else.
 * 2. `running` — the three fast reads (`overview`, `lineup`, `reviews`) go out together, then
 *    the ICP/persona turn (`synthesis`) follows once they have answered. `empty` is a CORRECT
 *    terminal for a step nobody could answer, not a failure, so the reviews step ends there.
 * 3. `complete` — the four FAST steps finished; this is the release-into-the-app signal. The
 *    script **ends here**, where the screen's life ends: the hook releases on this frame and
 *    never polls again.
 *
 * The release frame also carries a `succeeded` brand-kit ingestion job — the design ingestion
 * fires with the run and has normally published its draft kit by the release, so the checklist's
 * brand-kit row really does reach `complete` on the preview path too.
 *
 * The release frame deliberately carries the background work that outlives it — a `persona` step
 * running and a `product_research` step queued — because that is what the lane really serves at
 * release, and it is what makes the audience row say personas continue. Nothing past the release
 * is scripted: those frames are unreachable through the hook, and inventing them would be a lie
 * about the wire.
 */

import { SetupStatusSchema, type SetupStatus, type SetupStep } from "./setup";

/** One step in the wire shape, explicit nulls included — a partial would not be the wire. */
function step(
  kind: string,
  status: SetupStep["status"],
  phase: SetupStep["phase"] = "fast",
  subjectRef: string | null = null,
): SetupStep {
  return {
    kind,
    status,
    phase,
    subjectRef,
    startedAt: null,
    finishedAt: null,
    costUsd: "0",
    failureCode: null,
  };
}

const frame = (
  status: SetupStatus["status"],
  steps: SetupStep[],
  brandKit: SetupStatus["brand_kit_ingestion"] = null,
): SetupStatus =>
  SetupStatusSchema.parse({
    status,
    run_id: "run-fixture",
    steps,
    brand_kit_ingestion: brandKit,
  });

/**
 * A scripted new-lane run: queued → the three fast reads in parallel → the ICP turn → release,
 * with personas and per-product research continuing in the background after the release frame.
 *
 * Frame-per-read: the fixture source hands out the next frame on every poll and sticks at the
 * last one — a stream that has run out of states does not invent more.
 */
export const FIXTURE_SETUP_PROGRESS_SCRIPT: readonly SetupStatus[] = [
  frame("starting", []),
  frame("running", [
    step("overview", "running"),
    step("lineup", "running"),
    step("reviews", "running"),
  ]),
  frame("running", [
    step("overview", "completed"),
    step("lineup", "completed"),
    step("catalog_sync", "completed"),
    step("reviews", "empty"),
    step("synthesis", "running"),
  ]),
  frame(
    "complete",
    [
      step("overview", "completed"),
      step("lineup", "completed"),
      step("catalog_sync", "completed"),
      step("reviews", "empty"),
      step("synthesis", "completed"),
      step("persona", "running", "background", "clue-abm-buyers"),
      step("product_research", "queued", "background", "prd-1"),
    ],
    // The release frame carries a PUBLISHED brand kit: `POST /onboarding` fires the ingestion
    // at the same moment the run starts, and `GET /onboarding/current` serves the job, so by
    // the release the row has really moved. A fixture that left it null would preview a row
    // that never moves — the exact defect the live read exists to close.
    { job_id: "job-fixture", status: "succeeded" },
  ),
];
