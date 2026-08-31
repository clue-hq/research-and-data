import assert from "node:assert/strict";
import test from "node:test";
import {
  ONBOARDING_STEPS,
  authChoiceTarget,
  authSwitchTarget,
  onboardingStepHref,
} from "./onboarding-navigation";

test("onboarding navigation uses stable shareable routes", () => {
  assert.equal(onboardingStepHref("sign-in"), "/onboarding/sign-in");
  assert.equal(onboardingStepHref("verify-email"), "/onboarding/verify-email");
  assert.equal(onboardingStepHref("setting-up"), "/onboarding/setting-up");
});

test("the step set is the approved seven plus the ratified verify-email addition", () => {
  assert.deepEqual(ONBOARDING_STEPS, [
    "sign-in",
    "sign-in-email",
    "sign-up",
    "sign-up-email",
    "verify-email",
    "profile",
    "setting-up",
    "finalizing",
  ]);
});

test("auth choice and mode-switch targets are stable", () => {
  assert.equal(authChoiceTarget("sign-in", "email"), "sign-in-email");
  assert.equal(authChoiceTarget("sign-up", "email"), "sign-up-email");
  assert.equal(authChoiceTarget("sign-up", "google"), "profile");
  assert.equal(authSwitchTarget("sign-in-email"), "sign-up");
  assert.equal(authSwitchTarget("sign-up"), "sign-in");
});
