"use client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { CircleCheck, CircleAlert, X } from "lucide-react";
import styles from "./confirmation-card.module.css";
type Notice = { message: string; error: boolean; id: number };
const ConfirmationContext = createContext<
  (message: string, error?: boolean) => void
>(() => {});
export function useConfirmation() {
  return useContext(ConfirmationContext);
}
export function ConfirmationProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [notice, setNotice] = useState<Notice | null>(null);
  const show = useCallback(
    (message: string, error = false) =>
      setNotice({ message, error, id: Date.now() }),
    [],
  );
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 4000);
    return () => clearTimeout(timer);
  }, [notice]);
  return (
    <ConfirmationContext.Provider value={show}>
      {children}
      {notice ? (
        <div className={styles.card} role={notice.error ? "alert" : "status"}>
          {notice.error ? (
            <CircleAlert size={18} />
          ) : (
            <CircleCheck className={styles.success} size={18} />
          )}
          <span>{notice.message}</span>
          <button
            aria-label="Dismiss notification"
            onClick={() => setNotice(null)}
            type="button"
          >
            <X size={16} />
          </button>
        </div>
      ) : null}
    </ConfirmationContext.Provider>
  );
}
