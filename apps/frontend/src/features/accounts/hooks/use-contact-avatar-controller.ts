import { useMemo, useState } from "react";

/** Initials for the avatar fallback. An unnamed record gets a neutral mark, never a fake name. */
export function useContactAvatarController(name: string | null) {
  const [failed, setFailed] = useState(false);
  const initials = useMemo(() => {
    const parts = (name ?? "").split(/\s+/).filter(Boolean).slice(0, 2);
    if (!parts.length) return "?";
    return parts
      .map((part) => part[0])
      .join("")
      .toUpperCase();
  }, [name]);

  return { failed, initials, markFailed: () => setFailed(true) };
}
