import {
  SetupStatusSchema,
  readSetupStatus,
  startWorkspaceSetup,
  type SetupStatus,
} from "./setup";
import { FIXTURE_SETUP_PROGRESS_SCRIPT } from "./setup-progress.fixture";

/**
 * The setting-up flow's transport seam.
 *
 * `useSetupProgress` owns the lifecycle — start once, poll durable lane truth, release on the
 * fast steps' completion — and knows nothing about *where* the frames come from. Everything the
 * hook needs is these two calls, so a scripted local stream and the live BFF are interchangeable
 * without touching a line of the lifecycle.
 *
 * `start` takes the profile's company website because the onboarding lane is started FOR a
 * company: the live path derives the run's company domain from it. The fixture path ignores it —
 * a scripted stream has no company to research.
 */
export interface SetupProgressSource {
  start(input: { companyWebsite: string }): Promise<void>;
  read(): Promise<SetupStatus>;
}

/** The live path: the existing transport functions, unmoved and unwrapped. */
export const httpSetupProgressSource: SetupProgressSource = {
  start: startWorkspaceSetup,
  read: readSetupStatus,
};

/**
 * A scripted local stream over the same contract (the fixture adapter).
 *
 * Frame-per-read: each `read()` returns the next scripted frame and sticks at the last. The poll
 * tick is **transport simulation**, not a lifecycle model — nothing here advances a phase because
 * time passed, and a stream that has run out of states does not invent more. Every frame is parsed
 * through `SetupStatusSchema`, the same schema the HTTP adapter parses, so a fixture cannot drift
 * from the wire contract (and a frame's degradations — an unknown status, an additive key — are
 * exactly the ones the live path would apply).
 *
 * `start()` is not a read and consumes no frame: starting the run and observing it are separate
 * acts on the live path too.
 */
export function createFixtureSetupProgressSource(
  script: readonly SetupStatus[] = FIXTURE_SETUP_PROGRESS_SCRIPT,
): SetupProgressSource {
  if (script.length === 0) {
    // Fail at construction, loudly: a source that serves nothing would surface to the user as
    // "setup is taking longer than expected" — a fabricated diagnosis of a wiring mistake.
    throw new Error("A fixture setup-progress script needs at least one frame.");
  }
  let cursor = 0;
  return {
    async start() {
      // No-op, and the company website is deliberately ignored: the scripted stream's first
      // frame already reflects a started run, and it researches nobody.
    },
    async read() {
      const frame = script[cursor];
      if (cursor < script.length - 1) cursor += 1;
      return SetupStatusSchema.parse(frame);
    },
  };
}
