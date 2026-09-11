import { useMarkdownSourceEditor } from "../hooks/use-markdown-source-editor";
import styles from "./brand-context.module.css";

export default function MarkdownSourceEditor({
  value,
  onChange,
  readOnly,
}: {
  value: string;
  onChange: (value: string) => void;
  readOnly: boolean;
}) {
  const container = useMarkdownSourceEditor(value, onChange, readOnly);
  return <div className={styles.markdownEditor} ref={container} />;
}
