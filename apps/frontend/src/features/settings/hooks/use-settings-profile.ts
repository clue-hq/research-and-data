"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAutosaveField } from "./use-autosave-field";
import {
  patchSettingsProfile,
  patchSettingsWorkspace,
} from "../data/settings.actions";
import type { SettingsProfile } from "../model/profile";
import type { SettingsOrganization } from "../model/workspace";

export function useSettingsProfile(initial: SettingsProfile) {
  const [profile, setProfile] = useState(initial);
  const router = useRouter();
  const fullName = useAutosaveField(
    initial.full_name,
    async (value) => {
      const updated = await patchSettingsProfile({ full_name: value });
      setProfile((current) => ({
        ...current,
        first_name: updated.first_name,
        last_name: updated.last_name,
        full_name: updated.full_name,
      }));
      router.refresh();
      return updated.full_name;
    },
    "Profile updated",
  );
  const displayName = useAutosaveField(
    initial.display_name ?? "",
    async (value) => {
      const updated = await patchSettingsProfile({
        display_name: value || null,
      });
      setProfile((current) => ({
        ...current,
        display_name: updated.display_name,
      }));
      router.refresh();
      return updated.display_name ?? "";
    },
    "Profile updated",
  );
  return { profile, fullName, displayName };
}
export function useSettingsWorkspace(initial: SettingsOrganization) {
  const router = useRouter();
  const name = useAutosaveField(
    initial.name,
    async (value) => {
      const updated = await patchSettingsWorkspace(value);
      router.refresh();
      return updated.name;
    },
    "Workspace updated",
  );
  return { workspace: initial, name };
}
