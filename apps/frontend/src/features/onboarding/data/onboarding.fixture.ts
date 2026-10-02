import type { OnboardingFlow } from "../model/onboarding";

export const onboardingFixture: OnboardingFlow = {
  account: {
    email: "hello@aakash.design",
    firstName: "Aakash",
    lastName: "Shrivastava",
    role: "Founder",
    companyName: "Company",
    companyWebsite: "www.company.com",
  },
  auth: {
    signIn: {
      title: "Login to your account",
      accountPrompt: "Don’t have an account?",
      accountAction: "Sign up",
      googleLabel: "Continue with Google",
      emailLabel: "Continue with email",
      submitLabel: "Sign in",
    },
    signUp: {
      title: "Create a new account",
      accountPrompt: "Already have an account?",
      accountAction: "Sign in",
      googleLabel: "Continue with Google",
      emailLabel: "Continue with email",
      submitLabel: "Sign up",
    },
    verifyEmail: {
      title: "Verify your email",
      subtitle: "Enter the code we just sent to",
      codeLabel: "Verification code",
      submitLabel: "Verify",
      resendPrompt: "Didn’t get a code?",
      resendAction: "Resend",
    },
  },
  profile: {
    title: "Welcome to Clue!",
    subtitle: "Let’s get you setup.",
    roleOptions: ["Founder", "Marketing", "Sales", "Product", "Other"],
  },
  setup: {
    title: "Setting up your workspace, this will take a few minutes...",
    finalizingDetail: "Setting up company brand kit...",
    items: [
      {
        id: "company",
        label: "Understanding your company",
        detail: "Positioning, market and competitors",
        status: "complete",
      },
      {
        id: "products",
        label: "Your product lineup",
        detail: "Every offering, from your own pages",
        status: "running",
      },
      {
        id: "proof",
        label: "Customer proof",
        detail: "Reviews, case studies and named customers",
        status: "queued",
      },
      {
        id: "audience",
        label: "ICPs and personas",
        detail: "Who you sell to, and who decides",
        status: "queued",
      },
      {
        id: "brand-kit",
        label: "Creating brand kit",
        detail: "Colors, typography, tone & voice",
        status: "running",
      },
    ],
  },
};
