import type { InputHTMLAttributes, ReactNode } from "react";
import styles from "./checkbox-field.module.css";

export function CheckboxField({ children, className = "", ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { children: ReactNode }) {
  return <label className={`${styles.field} ${className}`}>
    <input {...props} className={styles.input} type="checkbox" />
    <span className={styles.label}>{children}</span>
  </label>;
}
