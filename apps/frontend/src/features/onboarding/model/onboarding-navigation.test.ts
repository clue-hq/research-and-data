import assert from "node:assert/strict";
import test from "node:test";
import {
  authChoiceTarget,
  authSwitchTarget,
  onboardingStepHref,
  submitTarget,
} from "./onboarding-navigation";

test("onboarding navigation uses stable shareable routes", () => {
  assert.equal(onboardingStepHref("sign-in"), "/onboarding/sign-in");
  assert.equal(onboardingStepHref("verify-email"), "/onboarding/verify-email");
  assert.equal(onboardingStepHref("setting-up"), "/onboarding/setting-up");
});

test("auth screens follow the approved flow plus the verify-email addition", () => {
  assert.equal(authChoiceTarget("sign-in", "email"), "sign-in-email");
  assert.equal(authChoiceTarget("sign-up", "google"), "profile");
  assert.equal(authSwitchTarget("sign-in-email"), "sign-up");
  // Sign-up now verifies the address before the profile step (FI-4 §9 ruling 2026-08-12);
  // sign-in still lands on profile in fixture mode and /session/establish in clerk mode.
  assert.equal(submitTarget("sign-in-email"), "profile");
  assert.equal(submitTarget("sign-up-email"), "verify-email");
  assert.equal(submitTarget("verify-email"), "profile");
  assert.equal(submitTarget("profile"), "setting-up");
  assert.equal(submitTarget("finalizing"), null);
});
