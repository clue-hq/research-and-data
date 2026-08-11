import assert from "node:assert/strict";
import test from "node:test";
import {
  ProvisionedWorkspaceSchema,
  validateProfileDraft,
  type OnboardingDraft,
} from "./onboarding";

const COMPLETE_DRAFT: OnboardingDraft = {
  email: "a@b.co",
  password: "pw",
  verificationCode: "",
  firstName: "Aakash",
  lastName: "Shrivastava",
  role: "Founder",
  companyName: "Insight Health",
  companyWebsite: "insight.health",
};

test("profile validation demands every field in clerk mode", () => {
  assert.equal(validateProfileDraft(COMPLETE_DRAFT), null);
  assert.match(
    validateProfileDraft({ ...COMPLETE_DRAFT, firstName: "  " }) ?? "",
    /first and last name/,
  );
  assert.match(validateProfileDraft({ ...COMPLETE_DRAFT, role: "" }) ?? "", /role/);
  assert.match(
    validateProfileDraft({ ...COMPLETE_DRAFT, companyName: "" }) ?? "",
    /company name/,
  );
  assert.match(
    validateProfileDraft({ ...COMPLETE_DRAFT, companyWebsite: "" }) ?? "",
    /website/,
  );
});

test("an additive backend field never fails a successful provision (no strict parse)", () => {
  const parsed = ProvisionedWorkspaceSchema.parse({
    user_id: "usr_1",
    workspace_id: "ws_1",
    brand_id: "brd_1",
    membership_id: "wsm_1",
    role_key: "owner",
    company_name: "Insight Health",
    company_website: null,
    first_name: "Aakash",
    last_name: "Shrivastava",
    job_role: "Founder",
    created: true,
    some_future_field: "ignored",
  });
  assert.equal(parsed.workspace_id, "ws_1");
  assert.equal(parsed.company_name_ignored, false);
});
