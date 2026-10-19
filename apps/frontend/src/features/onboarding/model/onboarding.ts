import { z } from "zod";

export const OnboardingStepSchema = z.enum([
  "sign-in",
  "sign-in-email",
  "sign-up",
  "sign-up-email",
  "verify-email",
  "profile",
  "setting-up",
  "finalizing",
]);

const AuthScreenSchema = z.object({
  title: z.string().min(1),
  accountPrompt: z.string().min(1),
  accountAction: z.string().min(1),
  googleLabel: z.string().min(1),
  emailLabel: z.string().min(1),
  submitLabel: z.string().min(1),
});

const VerifyEmailScreenSchema = z.object({
  title: z.string().min(1),
  subtitle: z.string().min(1),
  codeLabel: z.string().min(1),
  submitLabel: z.string().min(1),
  resendPrompt: z.string().min(1),
  resendAction: z.string().min(1),
});

const SetupItemSchema = z.object({
  id: z.string().min(1),
  label: z.string().min(1),
  detail: z.string().min(1).optional(),
  status: z.enum(["complete", "running", "queued"]),
});

export const OnboardingFlowSchema = z.object({
  account: z.object({
    email: z.string().email(),
    firstName: z.string().min(1),
    lastName: z.string().min(1),
    role: z.string().min(1),
    companyName: z.string().min(1),
    companyWebsite: z.string().min(1),
  }),
  auth: z.object({
    signIn: AuthScreenSchema,
    signUp: AuthScreenSchema,
    verifyEmail: VerifyEmailScreenSchema,
  }),
  profile: z.object({
    title: z.string().min(1),
    subtitle: z.string().min(1),
    roleOptions: z.array(z.string().min(1)).min(1),
  }),
  setup: z.object({
    title: z.string().min(1),
    finalizingDetail: z.string().min(1),
    items: z.array(SetupItemSchema).min(1),
  }),
});

export type OnboardingFlow = z.infer<typeof OnboardingFlowSchema>;
export type OnboardingStep = z.infer<typeof OnboardingStepSchema>;
export type SetupItem = z.infer<typeof SetupItemSchema>;

export type OnboardingDraft = OnboardingFlow["account"] & {
  password: string;
  verificationCode: string;
};

export function isOnboardingStep(value: string): value is OnboardingStep {
  return OnboardingStepSchema.safeParse(value).success;
}

/**
 * Headless authentication seam (FI-4 D-1, ratified): the frozen screens own every pixel; the
 * adapter owns credentials and sessions. The Clerk adapter drives Clerk's custom flows; the
 * fixture adapter preserves the design-review navigation theatre when authentication is off.
 */
export type OnboardingAuthResult =
  | {
      status: "complete";
      /**
       * Which credential flow just completed. The controller routes on it: a
       * completed sign-IN establishes the session; a completed sign-UP
       * continues to profile/provisioning. Optional because the fixture
       * adapter's theatre has no real flow to report.
       */
      flow?: "sign-in" | "sign-up";
    }
  | {
      status: "needs-verification";
      purpose: "sign-up" | "device-trust" | "second-factor";
    }
  | { status: "error"; message: string };

export type OnboardingGoogleAuthResult = OnboardingAuthResult | { status: "redirecting" };

export type InvitationSignUpInput = {
  ticket: string;
  firstName: string;
  lastName: string;
  password: string;
};

export interface OnboardingAuthAdapter {
  mode: "clerk" | "fixture";
  /** The authenticated email once a session exists (null before sign-in / in fixture mode). */
  email: string | null;
  /** The email of the in-progress sign-up attempt, if any (survives a page refresh). */
  pendingEmail: string | null;
  signInWithPassword(
    email: string,
    password: string,
  ): Promise<OnboardingAuthResult>;
  signUpWithPassword(
    email: string,
    password: string,
  ): Promise<OnboardingAuthResult>;
  acceptInvitation?(params: InvitationSignUpInput): Promise<OnboardingAuthResult>;
  verifyEmailCode(code: string): Promise<OnboardingAuthResult>;
  resendEmailCode(): Promise<OnboardingAuthResult>;
  signInWithGoogle(): Promise<OnboardingGoogleAuthResult>;
  signOut(): Promise<void>;
}

/** Wire shapes for POST /api/onboarding/provision (mirrors backend /auth/v1/provision). */
export const ProvisionWorkspaceInputSchema = z.object({
  first_name: z.string().min(1).max(200),
  last_name: z.string().min(1).max(200),
  job_role: z.string().min(1).max(200),
  // Optional: left null, the workspace is named from the website's own name.
  company_name: z.string().min(1).max(200).nullable(),
  company_website: z.string().max(2000).nullable(),
});

// Deliberately NOT .strict(): an additive backend field must never turn a successful
// provision into a client-side failure (review finding FE13).
export const ProvisionedWorkspaceSchema = z.object({
  user_id: z.string().min(1),
  workspace_id: z.string().min(1),
  brand_id: z.string().min(1),
  membership_id: z.string().min(1),
  role_key: z.string().min(1),
  company_name: z.string().min(1),
  company_website: z.string().nullable(),
  first_name: z.string().nullable(),
  last_name: z.string().nullable(),
  job_role: z.string().nullable(),
  created: z.boolean(),
  // True when a replay's submitted company name diverged from the recorded workspace name
  // (names are fixed at creation; the backend refuses to pretend a rename happened).
  company_name_ignored: z.boolean().optional().default(false),
});

export type ProvisionWorkspaceInput = z.infer<
  typeof ProvisionWorkspaceInputSchema
>;
export type ProvisionedWorkspace = z.infer<typeof ProvisionedWorkspaceSchema>;

/** Profile-screen validation, extracted so it is unit-testable (review finding FE9). */
export function validateProfileDraft(draft: OnboardingDraft): string | null {
  if (!draft.firstName.trim() || !draft.lastName.trim()) {
    return "Please enter your first and last name.";
  }
  if (!draft.role.trim()) return "Please select your role.";
  // The company name is optional — a blank one is filled from the website.
  if (!draft.companyWebsite.trim()) return "Please enter your company website.";
  return null;
}
