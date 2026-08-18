// The frozen D-6 checklist table is static configuration, not a repository/fixture — the
// `**/data/**` import ban is scoped to presentation components (eslint.config.mjs), and the
// derivation below still takes the table as a parameter; this import only supplies its default.
import { SETUP_GROUPS, type SetupGroup } from "../data/setup-groups";
import type { OnboardingFlow, SetupItem } from "./onboarding";

/** The fixture id of the brand-kit row, whose status is derived from the workspace's real
 * design brand-kit ingestion job since brand-kit slice 3 (fails loudly in tests if the fixture
 * renames it — review FE-N9). The fixture still owns the row's identity (id, label, detail);
 * only its status/detail derivation is live. */
export const BRAND_KIT_ITEM_ID = "brand-kit";

/** The lane name whose field work is, by construction, a second pass: the background lane only
 * starts once the fast lane is done, and it re-derives what the capped fast lane already had. */
const BACKGROUND_LANE = "background";

/** A per-field progress state, structurally typed so this pure model never imports transport.
 * `data/setup.ts`'s `SetupFieldState` satisfies it. */
export interface SetupFieldSnapshot {
  field_key: string;
  lane: string;
  status: "started" | "resolved" | "empty" | "failed";
}

/** The workspace's brand-kit ingestion job as the backend serves it (brand-kit slice 3): honest
 * job truth, never a pre-derived row status. `data/setup.ts`'s parsed value satisfies it. */
export interface SetupBrandKitJobSnapshot {
  job_id: string;
  status: string;
}

/** What the derivation needs from a poll tick. Structural: the full `SetupStatus` satisfies it. */
export interface SetupProgressSnapshot {
  status: string;
  // Lane truth is NOT redundant with `status`: the backend collapses every non-failed,
  // non-completed fast lane to overall "running", so a PAUSED lane is visible only here.
  fast_status?: string | null;
  background_status?: string | null;
  fields?: readonly SetupFieldSnapshot[];
  fast_budget_exhausted?: boolean | null;
  background_budget_exhausted?: boolean | null;
  // Absent (a pre-brand-kit-slice-3 backend) and null (no job row) mean the same thing: there is
  // no ingestion to report. The recon reduction above never reads it — the two are unrelated
  // work, and the brand-kit row is not one of the D-6 groups.
  brand_kit_ingestion?: SetupBrandKitJobSnapshot | null;
}

/** A field is finished when it has an answer, has no answer anyone could find (`empty` is a
 * CORRECT outcome, not a failure), or its attempt errored. None of the three is pending work. */
const TERMINAL = new Set<SetupFieldSnapshot["status"]>(["resolved", "empty", "failed"]);

/**
 * Overall statuses after which nothing is running any more — `useSetupProgress` stops polling
 * on both and surfaces them with recovery controls.
 */
const HALTED_OVERALL = new Set(["failed", "unavailable"]);

/**
 * Detail-line annotations. The frozen `SetupItemSchema.status` vocabulary
 * (complete/running/queued) is the ONLY visual state there is, so every nuance — failure,
 * budget exhaustion, a background re-run — is carried as copy on the detail line (the slice-2
 * precedent). At most one is appended per row: a second clause would churn the `aria-live`
 * region for no added truth.
 */
export const FAILED_MEMBER_ANNOTATION = " — part of this hit a problem";
export const BUDGET_STOP_ANNOTATION = " — stopped at the research budget";
export const DEEPENING_ANNOTATION = " — deepening research";

/**
 * Map one durable recon-lane status onto the frozen three-state checklist vocabulary.
 * `failed`/`paused` deliberately do NOT map to `queued` (that would assert "this will
 * happen"); callers drop or annotate those rows instead (review FE-M3).
 *
 * Slice 3 derives a row's *shape* from per-field events, but lane status still decides whether
 * anything is executing at all (see `isHalted`). This stays the one place the lane vocabulary
 * is decoded.
 */
export function laneItemStatus(lane: string | null): SetupItem["status"] | "stopped" {
  if (lane === "completed") return "complete";
  if (lane === "running") return "running";
  if (lane === "failed" || lane === "paused") return "stopped";
  return "queued";
}

/**
 * Reduce one group's member field events into the frozen checklist vocabulary (pure).
 *
 * - No member has been reached yet → `queued` (nothing has happened, and nothing is claimed).
 * - Every reached member is terminal and none is missing → `complete`.
 * - Anything in between → `running`.
 * - `status === "complete"` (the fast lane finished — the release-into-the-app signal) forces
 *   `complete`, so the screen the user is released from never contradicts the release.
 * - A halted run demotes an unfinished group to `queued`: nothing is running any more, so a
 *   spinner would be fabricated motion (see `isHalted` for the two axes it reads).
 *
 * The backend has already reduced the event stream to one entry per field; this must NOT
 * re-reduce (it never sees the event `seq`).
 */
export function groupStatus(
  fields: readonly SetupFieldSnapshot[],
  group: SetupGroup,
  progress: SetupProgressSnapshot,
): SetupItem["status"] {
  return reduceMembers(memberStates(fields, group), progress);
}

/**
 * Is the run stopped — i.e. would a spinner be fabricated motion?
 *
 * Two independent axes, because neither implies the other:
 *
 * 1. The overall status is terminal (`failed` / `unavailable`) — the poll loop has stopped.
 * 2. The FAST lane is stopped (`failed` / `paused` — `laneItemStatus`, review FE-M3). The
 *    backend collapses every fast lane that is neither failed nor completed to overall
 *    `running`, so a PAUSED lane is invisible on axis 1 and would otherwise spin forever.
 *    Slice 2 rendered exactly this case as `queued`; slice 3 keeps that ruling.
 *
 * …unless the BACKGROUND lane is executing right now: the lanes are sequential, and the driver
 * picks the background lane up once the fast lane leaves queued/running, so a stopped fast lane
 * with a live background lane is genuine motion.
 *
 * A stopped background lane needs no case of its own: it can only matter once the fast lane is
 * done, and a completed fast lane is overall `complete`, which forces every group `complete`
 * before this is consulted. Demoting a released run's rows would contradict the release.
 */
function isHalted(progress: SetupProgressSnapshot): boolean {
  if (HALTED_OVERALL.has(progress.status)) return true;
  if (laneItemStatus(progress.fast_status ?? null) !== "stopped") return false;
  return laneItemStatus(progress.background_status ?? null) !== "running";
}

function reduceMembers(
  member: readonly (SetupFieldSnapshot | null)[],
  progress: SetupProgressSnapshot,
): SetupItem["status"] {
  if (progress.status === "complete") return "complete";
  const reached = member.some((state) => state !== null);
  const finished =
    reached && member.every((state) => state !== null && TERMINAL.has(state.status));
  if (finished) return "complete";
  // Unfinished: `running` only while something is actually running.
  return reached && !isHalted(progress) ? "running" : "queued";
}

function memberStates(
  fields: readonly SetupFieldSnapshot[],
  group: SetupGroup,
): (SetupFieldSnapshot | null)[] {
  return group.fieldKeys.map(
    (key) => fields.find((state) => state.field_key === key) ?? null,
  );
}

/**
 * Pick the single honest annotation for a group, in priority order.
 *
 * 1. A failed member — the most consequential thing that can have happened to the group.
 * 2. A member no lane reached while a lane reported its budget exhausted: the honest reason
 *    the row is not going to fill from this pass, rather than a silent gap. (`null` means the
 *    verdict is unknown and is never read as `false` — no fabricated budget claim.)
 * 3. Every member reached, and all still-running work belongs to the background lane: the
 *    group already had its pass and is being revisited, so it must not read as a bare restart
 *    (the cross-lane regression `resolved → started` is honest, and this says why). Withheld
 *    when the fast lane hit its cap — a background `started` may then be FIRST contact with
 *    that field rather than a second pass, and we do not guess.
 */
function annotationFor(
  member: readonly (SetupFieldSnapshot | null)[],
  progress: SetupProgressSnapshot,
): string {
  if (member.some((state) => state?.status === "failed")) return FAILED_MEMBER_ANNOTATION;
  const budgetStopped =
    progress.fast_budget_exhausted === true || progress.background_budget_exhausted === true;
  if (budgetStopped && member.some((state) => state === null)) return BUDGET_STOP_ANNOTATION;
  const inFlight = member.filter(
    (state): state is SetupFieldSnapshot => state !== null && !TERMINAL.has(state.status),
  );
  if (
    progress.fast_budget_exhausted !== true &&
    member.every((state) => state !== null) &&
    inFlight.length > 0 &&
    inFlight.every((state) => state.lane === BACKGROUND_LANE)
  ) {
    return DEEPENING_ANNOTATION;
  }
  return "";
}

/**
 * Map the workspace's brand-kit ingestion job onto the frozen three-state row vocabulary
 * (brand-kit slice 3). Pure; the fixture keeps the row's identity, this decides only its state.
 *
 * | job | row | why |
 * | --- | --- | --- |
 * | absent / null | `queued` | no ingestion exists (or a backend that predates the field) |
 * | `queued` / `running` | `running` | the fleet holds real work for this workspace |
 * | `succeeded` | `complete` | a draft kit was published |
 * | `failed` | `queued` + failure annotation | see below |
 *
 * A failed job is NOT `complete`: that would claim a kit exists when nothing was produced. The
 * row vocabulary has no failed state, so the failure rides the detail line exactly as a failed
 * recon field annotates its group, and brand-kit slice 4's manual trigger is the rescue path.
 * An unrecognized (future) status reads as in-flight — the same degradation the per-field
 * status takes (review FE-N2) — never as a kit that exists.
 */
function brandKitItem(row: SetupItem, job: SetupBrandKitJobSnapshot | null): SetupItem {
  if (job === null) return { ...row, status: "queued" };
  if (job.status === "succeeded") return { ...row, status: "complete" };
  if (job.status === "failed") {
    return { ...row, status: "queued", detail: `${row.detail}${FAILED_MEMBER_ANNOTATION}` };
  }
  return { ...row, status: "running" };
}

/**
 * Derive the honest checklist rows from durable recon truth (pure; unit-tested).
 *
 * Rows are the D-6 groups (passed in, defaulting to the ratified table) plus the brand-kit row.
 * Row ids are constants, so the `aria-live` list keeps stable keys across every tick.
 *
 * - `starting` with no field event yet renders the FIRST group as running: the submission is
 *   durably captured and the drive is in flight (review FE-M1/BE-M6). It is a real durable
 *   signal, not a timer — and the first real event supersedes it.
 * - The brand-kit row reports the workspace's real ingestion job (`brandKitItem`), and is
 *   dropped cleanly if the fixture no longer carries it. It is deliberately outside the group
 *   reduction: the ingestion is separate work from recon, so neither lane truth nor the
 *   index-0 warm-up rule touches it.
 */
export function deriveSetupItems(
  fixtureSetup: OnboardingFlow["setup"],
  progress: SetupProgressSnapshot | null,
  groups: readonly SetupGroup[] = SETUP_GROUPS,
): SetupItem[] {
  const fields = progress?.fields ?? [];
  // The warm-up placeholder only stands in for the absence of events; once ANY field has
  // reported, event truth drives every row.
  const warmingUp = progress?.status === "starting" && fields.length === 0;

  const items: SetupItem[] = groups.map((group, index) => {
    const member = memberStates(fields, group);
    const status = reduceMembers(member, progress ?? { status: "" });
    // `progress` is only null before the first poll — there is nothing to annotate then, and
    // the annotator needs a tick to read.
    const annotation = progress === null ? "" : annotationFor(member, progress);
    return {
      id: group.id,
      label: group.label,
      detail: `${group.detail}${annotation}`,
      status: warmingUp && index === 0 && status === "queued" ? "running" : status,
    };
  });

  const brandKit = fixtureSetup.items.find((item) => item.id === BRAND_KIT_ITEM_ID);
  if (brandKit) {
    items.push(brandKitItem(brandKit, progress?.brand_kit_ingestion ?? null));
  }
  return items;
}
