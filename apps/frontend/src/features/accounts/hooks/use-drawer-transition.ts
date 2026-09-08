import { useEffect, useRef, useState, type AnimationEvent } from "react";

export function useDrawerTransition() {
  const [closing, setClosing] = useState(false);
  const afterExit = useRef<(() => void) | null>(null);

  function finish() {
    const action = afterExit.current;
    afterExit.current = null;
    action?.();
  }

  function close(action: () => void) {
    if (afterExit.current) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      action();
      return;
    }
    afterExit.current = action;
    setClosing(true);
  }

  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const changed = () => { if (preference.matches) finish(); };
    preference.addEventListener("change", changed);
    return () => preference.removeEventListener("change", changed);
  }, []);

  function onAnimationEnd(event: AnimationEvent<HTMLElement>) {
    if (event.target === event.currentTarget && closing) finish();
  }

  return { close, closing, onAnimationEnd };
}
