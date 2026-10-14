import Link from "next/link";
import type { ProductNotice } from "../model/product-notice";
import styles from "./project-flow.module.css";

/**
 * "Products changed" lines above the chat (spec 2026-10-15 §7): a merge or removal in Brand
 * context moved this project's products. One line per change, until this person dismisses it.
 */
export function ProductNotices({
  notices, onDismiss,
}: {
  notices: readonly ProductNotice[];
  onDismiss: (changeId: string) => void;
}) {
  if (!notices.length) return null;
  return (
    <div className={styles.productNotices}>
      {notices.map((notice) => (
        <div className={styles.productNotice} key={notice.changeId} role="status">
          <p>{notice.text}</p>
          <Link className={styles.productNoticeLink} href="/brand-context?section=knowledge&file=product/catalog.md">
            Review in Brand context
          </Link>
          <button className={styles.productNoticeDismiss} onClick={() => onDismiss(notice.changeId)} type="button">
            Dismiss
          </button>
        </div>
      ))}
    </div>
  );
}
