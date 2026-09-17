import { useMemo, useState } from "react";

export function useContactAvatarController(name: string) {
  const [failed, setFailed] = useState(false);
  const initials = useMemo(
    () =>
      name
        .split(/\s+/)
        .slice(0, 2)
        .map((part) => part[0])
        .join("")
        .toUpperCase(),
    [name],
  );

  return { failed, initials, markFailed: () => setFailed(true) };
}
