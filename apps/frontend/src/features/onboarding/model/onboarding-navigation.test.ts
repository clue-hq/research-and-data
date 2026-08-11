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
  assert.equal(onboardingStepHref("setting-up"), "/onboarding/setting-up");
});

test("auth screens follow the approved seven-screen flow", () => {
  assert.equal(authChoiceTarget("sign-in", "email"), "sign-in-email");
  assert.equal(authChoiceTarget("sign-up", "google"), "profile");
  assert.equal(authSwitchTarget("sign-in-email"), "sign-up");
  assert.equal(submitTarget("sign-up-email"), "profile");
  assert.equal(submitTarget("profile"), "setting-up");
  assert.equal(submitTarget("finalizing"), null);
});
