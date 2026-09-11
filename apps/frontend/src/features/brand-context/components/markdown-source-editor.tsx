import { useMarkdownSourceEditor } from "../hooks/use-markdown-source-editor";
import styles from "./brand-context.module.css";

export default function MarkdownSourceEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const container = useMarkdownSourceEditor(value, onChange);
  return <div className={styles.markdownEditor} ref={container} />;
}
