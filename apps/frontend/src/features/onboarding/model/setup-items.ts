// The frozen D-6 checklist table is static configuration, not a repository/fixture — the
// `**/data/**` import ban is scoped to presentation components (eslint.config.mjs), and the
// derivation below still takes the table as a parameter; this import only supplies its default.
import { SETUP_GROUPS, type SetupGroup } from "../data/setup-groups";
import type { OnboardingFlow, SetupItem } from "./onboarding";

/** The fixture id of the founder-ratified explicit-dummy brand-kit row (fails loudly in
 * tests if the fixture renames it — review FE-N9). */
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

/** What the derivation needs from a poll tick. Structural: the full `SetupStatus` satisfies it. */
export interface SetupProgressSnapshot {
  status: string;
  fields?: readonly SetupFieldSnapshot[];
  fast_budget_exhausted?: boolean | null;
  background_budget_exhausted?: boolean | null;
}

/** A field is finished when it has an answer, has no answer anyone could find (`empty` is a
 * CORRECT outcome, not a failure), or its attempt errored. None of the three is pending work. */
const TERMINAL = new Set<SetupFieldSnapshot["status"]>(["resolved", "empty", "failed"]);

/**
 * Overall statuses after which nothing is running any more — `useSetupProgress` stops polling
 * on both and surfaces them with recovery controls. A group left mid-flight by one of them
 * renders as unfinished (`queued`) rather than spinning on work no lane is doing: the frozen
 * vocabulary has no "stopped" state, and the surfaced failure paragraph carries the why (the
 * slice-2 precedent for a stopped lane). "No fake progress" applies to the end of a run too.
 */
const HALTED = new Set(["failed", "unavailable"]);

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
 * Slice 3 derives the rows from per-field events instead of lane status, so this is no longer
 * on the `deriveSetupItems` path; it stays the one place the lane vocabulary is decoded.
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
 * - `overall === "complete"` (the fast lane finished — the release-into-the-app signal) forces
 *   `complete`, so the screen the user is released from never contradicts the release.
 * - A halted overall status demotes an unfinished group to `queued`: nothing is running any
 *   more, so a spinner would be fabricated motion (see `HALTED`).
 *
 * The backend has already reduced the event stream to one entry per field; this must NOT
 * re-reduce (it never sees the event `seq`).
 */
export function groupStatus(
  fields: readonly SetupFieldSnapshot[],
  group: SetupGroup,
  overall: string,
): SetupItem["status"] {
  return reduceMembers(memberStates(fields, group), overall);
}

function reduceMembers(
  member: readonly (SetupFieldSnapshot | null)[],
  overall: string,
): SetupItem["status"] {
  if (overall === "complete") return "complete";
  const reached = member.some((state) => state !== null);
  const finished =
    reached && member.every((state) => state !== null && TERMINAL.has(state.status));
  if (finished) return "complete";
  // Unfinished: `running` only while something is actually running.
  return reached && !HALTED.has(overall) ? "running" : "queued";
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
 *    (the cross-lane regression `resolved → started` is honest, and this says why).
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
    member.every((state) => state !== null) &&
    inFlight.length > 0 &&
    inFlight.every((state) => state.lane === BACKGROUND_LANE)
  ) {
    return DEEPENING_ANNOTATION;
  }
  return "";
}

/**
 * Derive the honest checklist rows from durable recon truth (pure; unit-tested).
 *
 * Rows are the D-6 groups (passed in, defaulting to the ratified table) plus the brand-kit
 * dummy. Row ids are constants, so the `aria-live` list keeps stable keys across every tick.
 *
 * - `starting` with no field event yet renders the FIRST group as running: the submission is
 *   durably captured and the drive is in flight (review FE-M1/BE-M6). It is a real durable
 *   signal, not a timer — and the first real event supersedes it.
 * - The brand-kit row stays the ratified explicit dummy (forced `queued`), and is dropped
 *   cleanly if the fixture no longer carries it.
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
    const status = reduceMembers(member, progress?.status ?? "");
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
    // Founder ruling (FI-4 §9): explicit dummy until the design branch merges.
    items.push({ ...brandKit, status: "queued" });
  }
  return items;
}
