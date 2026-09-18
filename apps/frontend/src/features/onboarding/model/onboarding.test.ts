import assert from "node:assert/strict";
import test from "node:test";
import {
  ProvisionedWorkspaceSchema,
  ProvisionWorkspaceInputSchema,
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

test("profile validation demands every field but the company name in clerk mode", () => {
  assert.equal(validateProfileDraft(COMPLETE_DRAFT), null);
  assert.match(
    validateProfileDraft({ ...COMPLETE_DRAFT, firstName: "  " }) ?? "",
    /first and last name/,
  );
  assert.match(validateProfileDraft({ ...COMPLETE_DRAFT, role: "" }) ?? "", /role/);
  assert.match(
    validateProfileDraft({ ...COMPLETE_DRAFT, companyWebsite: "" }) ?? "",
    /website/,
  );
});

test("a blank company name is allowed: the website's own name is used instead", () => {
  // The workspace is named from the website when the field is left blank, so an
  // empty company name must not stop the profile screen.
  assert.equal(validateProfileDraft({ ...COMPLETE_DRAFT, companyName: "" }), null);
  assert.equal(validateProfileDraft({ ...COMPLETE_DRAFT, companyName: "   " }), null);
  assert.match(
    validateProfileDraft({ ...COMPLETE_DRAFT, companyName: "", companyWebsite: " " }) ?? "",
    /website/,
    "the website is what the name is derived from, so it is still required",
  );
});

test("provisioning accepts a null company name and refuses a blank one", () => {
  assert.equal(
    ProvisionWorkspaceInputSchema.parse({
      first_name: "Aakash",
      last_name: "Shrivastava",
      job_role: "Founder",
      company_name: null,
      company_website: "insight.health",
    }).company_name,
    null,
  );
  assert.equal(
    ProvisionWorkspaceInputSchema.safeParse({
      first_name: "Aakash",
      last_name: "Shrivastava",
      job_role: "Founder",
      company_name: "",
      company_website: "insight.health",
    }).success,
    false,
    "an empty string is not a name; omitting it means null",
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
