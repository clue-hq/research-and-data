// The checklist table is static configuration, not a repository/fixture — the `**/data/**`
// import ban is scoped to presentation components (eslint.config.mjs), and the derivation below
// still takes the table as a parameter; this import only supplies its default.
import { SETUP_GROUPS, type SetupGroup } from "../data/setup-groups";
import type { SetupStatus, SetupStep } from "../data/setup";
import type { OnboardingFlow, SetupItem } from "./onboarding";

/** The fixture id of the brand-kit row, whose status is derived from the workspace's real
 * design brand-kit ingestion job since brand-kit slice 3 (fails loudly in tests if the fixture
 * renames it — review FE-N9). The fixture still owns the row's identity (id, label, detail);
 * only its status/detail derivation is live. */
export const BRAND_KIT_ITEM_ID = "brand-kit";

/** The workspace's brand-kit ingestion job as the backend serves it (brand-kit slice 3): honest
 * job truth, never a pre-derived row status. `data/setup.ts`'s parsed value satisfies it. */
export interface SetupBrandKitJobSnapshot {
  job_id: string;
  status: string;
}

/**
 * Detail-line annotations. The frozen `SetupItemSchema.status` vocabulary
 * (complete/running/queued) is the ONLY visual state there is, so every nuance — a failure, work
 * that outlives the release — is carried as copy on the detail line (the slice-2 precedent). At
 * most one is appended per row: a second clause would churn the `aria-live` region for no added
 * truth.
 */
export const FAILED_MEMBER_ANNOTATION = " — part of this hit a problem";
/** The audience row's continuing-work note, re-exported from the table that now owns its text
 * (`SetupGroup.continuingNote`) so tests keep one name for it. */
export const CONTINUING_ANNOTATION =
  SETUP_GROUPS.find((group) => group.continuingNote)?.continuingNote ?? "";

/** A step is done when it answered, or when nobody could find an answer — `empty` is a CORRECT
 * outcome, not a failure. Neither is pending work. */
const STEP_DONE = new Set<SetupStep["status"]>(["completed", "empty"]);

/** Overall statuses after which nothing is running any more — `useSetupProgress` stops polling on
 * both and surfaces them with recovery controls, so a spinner would be fabricated motion. */
const HALTED_OVERALL = new Set(["failed", "unavailable"]);

/** The one step this row completes on (its first kind), or null before the lane reaches it. */
function leadStep(steps: readonly SetupStep[], group: SetupGroup): SetupStep | null {
  return steps.find((s) => s.kind === group.stepKinds[0]) ?? null;
}

/**
 * Reduce a row's steps into the frozen checklist vocabulary (pure).
 *
 * A row reports ONE lead step — the fast turn whose completion is the row's promise. Later kinds
 * on the same row (per-subject background work such as `persona`) only annotate: they can outlive
 * the release, so holding the row open for them would contradict releasing the user.
 *
 * - `status === "complete"` (the fast steps finished — the release-into-the-app signal) forces
 *   `complete`, so the screen the user is released from never contradicts the release.
 * - The lead step has not appeared → `queued`: nothing has happened, and nothing is claimed.
 * - A halted run never spins: the lead step's last-seen `running` is stale, not live motion.
 *
 * `progress` is structural on purpose — the full `SetupStatus` satisfies it, and so does the
 * no-tick-yet default the derivation passes.
 */
export function groupStatus(
  steps: readonly SetupStep[],
  group: SetupGroup,
  progress: { status: string },
): SetupItem["status"] {
  if (progress.status === "complete") return "complete";
  const lead = leadStep(steps, group);
  if (lead === null) return "queued";
  if (STEP_DONE.has(lead.status)) return "complete";
  if (lead.status === "running" && !HALTED_OVERALL.has(progress.status)) return "running";
  return "queued";
}

/**
 * Pick the single honest annotation for a row, in priority order.
 *
 * 1. Any step of this row failed — the most consequential thing that can have happened to it.
 * 2. The lead step is done and the row carries a `continuingNote`: the row's promise is kept,
 *    but work continues past it. The note stands until that trailing work has FINISHED — not
 *    until it appears. Persona steps are created only after `synthesis` completes, which is
 *    usually the very tick that releases the user, so requiring a live trailing step would mean
 *    the promise is made exactly when it cannot be rendered. An absent trailing step is
 *    "not finished", the same as a running one.
 */
function annotationFor(steps: readonly SetupStep[], group: SetupGroup): string {
  const mine = steps.filter((s) => group.stepKinds.includes(s.kind));
  if (mine.some((s) => s.status === "failed")) return FAILED_MEMBER_ANNOTATION;
  const lead = leadStep(steps, group);
  if (!lead || !STEP_DONE.has(lead.status) || !group.continuingNote) return "";
  const trailing = mine.filter((s) => s.kind !== group.stepKinds[0]);
  const finished = trailing.length > 0 && trailing.every((s) => STEP_DONE.has(s.status));
  return finished ? "" : group.continuingNote;
}

/**
 * Map the workspace's brand-kit ingestion job onto the frozen three-state row vocabulary
 * (brand-kit slice 3). Pure; the fixture keeps the row's identity, this decides only its state.
 *
 * | job | row | why |
 * | --- | --- | --- |
 * | absent / null | `queued` | no ingestion exists (or a backend that predates the field) |
 * | `queued` / `running` | `running` | the fleet holds real work for this workspace |
 * | `succeeded` / `succeeded_with_gaps` | `complete` | a draft kit was published (gaps or not) |
 * | `failed` | `queued` + failure annotation | see below |
 * | in flight, run halted | `queued` | see below |
 *
 * Once the run has HALTED (`failed` / `unavailable` — polling stops and recovery controls show),
 * an in-flight job reads `queued`: its last-seen `running` is stale, exactly as a halted run's
 * step rows stop spinning (`groupStatus`). Finished outcomes still show as they are. (First
 * production onboarding, 2026-10-03: research failed mid-ingestion and the row spun forever after
 * the kit had succeeded.)
 *
 * A failed job is NOT `complete`: that would claim a kit exists when nothing was produced. The
 * row vocabulary has no failed state, so the failure rides the detail line exactly as a failed
 * step annotates its row, and brand-kit slice 4's manual trigger is the rescue path. An
 * unrecognized (future) status reads as in-flight — the same degradation the per-step status
 * takes (review FE-N2) — never as a kit that exists.
 */
function brandKitItem(
  row: SetupItem,
  job: SetupBrandKitJobSnapshot | null,
  progress: { status: string },
): SetupItem {
  if (job === null) return { ...row, status: "queued" };
  if (job.status === "succeeded" || job.status === "succeeded_with_gaps") {
    return { ...row, status: "complete" };
  }
  if (job.status === "failed") {
    return { ...row, status: "queued", detail: `${row.detail}${FAILED_MEMBER_ANNOTATION}` };
  }
  return { ...row, status: HALTED_OVERALL.has(progress.status) ? "queued" : "running" };
}

/**
 * Derive the honest checklist rows from the onboarding lane's durable steps (pure; unit-tested).
 *
 * Rows are the checklist groups (passed in, defaulting to the ratified table) plus the brand-kit
 * row. Row ids are constants, so the `aria-live` list keeps stable keys across every tick.
 *
 * - An in-flight run (`starting` or `running`) with no step yet renders the FIRST group as
 *   running: the run row is durably captured and the drive is in flight (review FE-M1/BE-M6).
 *   It is a real durable signal, not a timer — and the first real step supersedes it.
 * - The brand-kit row reports the workspace's real ingestion job (`brandKitItem`), and is dropped
 *   cleanly if the fixture no longer carries it. It is deliberately outside the group reduction:
 *   the ingestion is separate work from the lane, so neither the step truth nor the index-0
 *   warm-up rule touches it.
 */
export function deriveSetupItems(
  fixtureSetup: OnboardingFlow["setup"],
  progress: SetupStatus | null,
  groups: readonly SetupGroup[] = SETUP_GROUPS,
): SetupItem[] {
  const steps = progress?.steps ?? [];
  // The warm-up placeholder only stands in for the absence of steps; once ANY step has reported,
  // step truth drives every row. Both in-flight statuses count: between `mark_run_running` and
  // the first `start_step` the run reports `running` with zero steps, and a checklist where
  // every row is queued and nothing spins would claim the lane had stalled.
  const warmingUp =
    (progress?.status === "starting" || progress?.status === "running") && steps.length === 0;

  const items: SetupItem[] = groups.map((group, index) => {
    const status = groupStatus(steps, group, progress ?? { status: "" });
    // `progress` is only null before the first poll — there is nothing to annotate then, and the
    // annotator needs a tick to read.
    const annotation = progress === null ? "" : annotationFor(steps, group);
    return {
      id: group.id,
      label: group.label,
      detail: `${group.detail}${annotation}`,
      status: warmingUp && index === 0 && status === "queued" ? "running" : status,
    };
  });

  const brandKit = fixtureSetup.items.find((item) => item.id === BRAND_KIT_ITEM_ID);
  if (brandKit) {
    items.push(
      brandKitItem(brandKit, progress?.brand_kit_ingestion ?? null, progress ?? { status: "" }),
    );
  }
  return items;
}
