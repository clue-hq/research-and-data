import { z } from "zod";

export const OnboardingStepSchema = z.enum([
  "sign-in",
  "sign-in-email",
  "sign-up",
  "sign-up-email",
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

export function isOnboardingStep(value: string): value is OnboardingStep {
  return OnboardingStepSchema.safeParse(value).success;
}
