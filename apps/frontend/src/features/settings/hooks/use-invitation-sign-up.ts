"use client";
import { useRef, useState } from "react";
import { useOnboardingAuth } from "@/features/onboarding/data/onboarding-auth";

export function useInvitationSignUp(ticket: string, token: string) {
  const auth = useOnboardingAuth();
  const busy = useRef(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(form: FormData) {
    if (busy.current) return;
    if (!auth.acceptInvitation) {
      setError("Invitation sign-up requires authentication to be configured.");
      return;
    }
    busy.current = true;
    setSaving(true);
    setError(null);
    try {
      const result = await auth.acceptInvitation({
        ticket,
        firstName: String(form.get("firstName") ?? "").trim(),
        lastName: String(form.get("lastName") ?? "").trim(),
        password: String(form.get("password") ?? ""),
      });
      if (result.status === "complete") {
        window.location.assign(
          `/session/establish?${new URLSearchParams({ invite: token })}`,
        );
      } else {
        setError(
          result.status === "error"
            ? result.message
            : "Complete your account verification, then reopen this invitation.",
        );
      }
    } catch {
      setError("Invitation sign-up is unavailable. Please try again.");
    } finally {
      busy.current = false;
      setSaving(false);
    }
  }
  return { saving, error, submit };
}
