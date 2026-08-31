"use client";

import { createContext, useCallback, useContext, useState } from "react";
import type { OnboardingDraft } from "../model/onboarding";

const EMPTY_DRAFT: OnboardingDraft = {
  email: "",
  password: "",
  verificationCode: "",
  firstName: "",
  lastName: "",
  role: "",
  companyName: "",
  companyWebsite: "",
};

interface OnboardingDraftContextValue {
  draft: OnboardingDraft;
  updateDraft: <Key extends keyof OnboardingDraft>(
    key: Key,
    value: OnboardingDraft[Key],
  ) => void;
}

const OnboardingDraftContext = createContext<OnboardingDraftContextValue | null>(null);

/**
 * Holds the onboarding draft above the per-step routes so navigating between steps no longer
 * loses what the user typed (the pre-integration screens remounted their state on every
 * transition). Memory-only by design — the password never touches storage.
 */
export function OnboardingDraftProvider({ children }: { children: React.ReactNode }) {
  const [draft, setDraft] = useState<OnboardingDraft>(EMPTY_DRAFT);
  const updateDraft = useCallback(
    <Key extends keyof OnboardingDraft>(key: Key, value: OnboardingDraft[Key]) => {
      setDraft((current) => ({ ...current, [key]: value }));
    },
    [],
  );
  return (
    <OnboardingDraftContext.Provider value={{ draft, updateDraft }}>
      {children}
    </OnboardingDraftContext.Provider>
  );
}

export function useOnboardingDraft(): OnboardingDraftContextValue {
  const value = useContext(OnboardingDraftContext);
  if (!value) {
    throw new Error("useOnboardingDraft requires an OnboardingDraftProvider ancestor");
  }
  return value;
}
