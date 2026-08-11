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
  | { status: "complete" }
  | { status: "needs-verification" }
  | { status: "error"; message: string };

export interface OnboardingAuthAdapter {
  mode: "clerk" | "fixture";
  /** The authenticated email once a session exists (null before sign-in / in fixture mode). */
  email: string | null;
  signInWithPassword(email: string, password: string): Promise<OnboardingAuthResult>;
  signUpWithPassword(email: string, password: string): Promise<OnboardingAuthResult>;
  verifyEmailCode(code: string): Promise<OnboardingAuthResult>;
  resendEmailCode(): Promise<OnboardingAuthResult>;
  signInWithGoogle(): Promise<OnboardingAuthResult>;
  signOut(): Promise<void>;
}

/** Wire shapes for POST /api/onboarding/provision (mirrors backend /auth/v1/provision). */
export const ProvisionWorkspaceInputSchema = z.object({
  first_name: z.string().min(1).max(200),
  last_name: z.string().min(1).max(200),
  job_role: z.string().min(1).max(200),
  company_name: z.string().min(1).max(200),
  company_website: z.string().max(2000).nullable(),
});

export const ProvisionedWorkspaceSchema = z
  .object({
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
  })
  .strict();

export type ProvisionWorkspaceInput = z.infer<typeof ProvisionWorkspaceInputSchema>;
export type ProvisionedWorkspace = z.infer<typeof ProvisionedWorkspaceSchema>;
