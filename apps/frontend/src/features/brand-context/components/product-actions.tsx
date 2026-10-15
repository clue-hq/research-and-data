"use client";

import { Menu } from "@base-ui/react/menu";
import type { ReactNode } from "react";
import type { ProductActionsController } from "../hooks/use-product-actions";
import type { BrandKnowledgeDocument } from "../model/brand-context";
import type { BrandProduct } from "../model/brand-knowledge";
import { PRODUCT_PAGE_KIND, canLinkProducts, linkedProductNames } from "../model/product-links";
import { BrandContextIcon } from "./brand-context-icon";
import styles from "./brand-context.module.css";

/** Rename, merge into and remove — the actions on one product's page in the Product folder. */
export function ProductMenu({ actions, product }: { actions: ProductActionsController; product: BrandProduct }) {
  if (!actions.canWrite) return null;
  return (
    <Menu.Root>
      <Menu.Trigger aria-label={`Actions for ${product.name}`} className={styles.productMenuTrigger}>
        <BrandContextIcon name="more" size={14} />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner align="start" className={styles.productMenuPositioner} sideOffset={4}>
          <Menu.Popup className={styles.productMenu}>
            <Menu.Item className={styles.productMenuItem} onClick={() => actions.open({ kind: "rename", product })}>
              <BrandContextIcon name="rename" size={14} />Rename product…
            </Menu.Item>
            <Menu.Item
              className={styles.productMenuItem}
              disabled={actions.products.length < 2}
              onClick={() => actions.open({ kind: "merge", product })}
            >
              <BrandContextIcon name="folderPlus" size={14} />Merge products into this one…
            </Menu.Item>
            <Menu.Separator className={styles.productMenuSeparator} />
            <Menu.Item className={styles.productMenuItem} onClick={() => actions.open({ kind: "remove", product })}>
              <BrandContextIcon name="trash" size={14} />Remove product…
            </Menu.Item>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}

/** The last row of the Product folder: add a product, and say what the last change did. */
export function ProductFolderFooter({ actions }: { actions: ProductActionsController }) {
  if (!actions.available || !actions.canWrite) return null;
  return (
    <div className={styles.productFolderFooter}>
      <button className={styles.productAddButton} onClick={() => actions.open({ kind: "add" })} type="button">
        <BrandContextIcon name="plus" size={12} />
        <span>Add product</span>
      </button>
      {actions.notice ? <p className={styles.productNotice} role="status">{actions.notice}.</p> : null}
    </div>
  );
}

/** Pending pages are listed by name so a product being written is visible. */
export function PendingProductPages({ actions }: { actions: ProductActionsController }) {
  const pending = actions.products.filter((product) => product.pagePending && !product.pageDocumentId);
  if (!pending.length) return null;
  return (
    <>
      {pending.map((product) => (
        <div className={styles.pendingProductPage} key={product.productId} role="status">
          <span aria-hidden="true" className={styles.documentTreeRule} />
          <BrandContextIcon className={styles.documentIcon} name="document" size={16} />
          <span className={styles.documentTitleText}>{product.name} — page being written</span>
        </div>
      ))}
    </>
  );
}

/** Shown above the catalog: it is generated, and here is what changed lately. */
export function ProductCatalogNotes({ actions }: { actions: ProductActionsController }) {
  return (
    <section aria-label="Product changes" className={styles.productCatalogNotes}>
      <p>
        This catalog is generated from your products. To change it, use Add product, or the
        actions on a product&rsquo;s page: rename, merge or remove.
      </p>
      {actions.recentChanges.length ? (
        <ul className={styles.recentProductChanges}>
          {actions.recentChanges.map((change) => (
            <li key={change.changeId}>
              <span>{change.text}</span>
              {change.undoable && actions.canWrite ? (
                <button
                  className={styles.secondaryButton}
                  disabled={actions.busy}
                  onClick={() => void actions.undo(change.changeId)}
                  type="button"
                >
                  Undo
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {actions.error && !actions.dialog ? <p className={styles.documentSaveError} role="alert">{actions.error}</p> : null}
    </section>
  );
}

/** The editor header's "Products" line: which products this document is about. */
export function DocumentProductsField({
  actions, document, disabled,
}: {
  actions: ProductActionsController;
  document: BrandKnowledgeDocument;
  disabled: boolean;
}) {
  if (!actions.available || !canLinkProducts(document)) return null;
  const names = linkedProductNames(document, actions.products);
  const label = names.length ? `Products: ${names.join(", ")}` : "No product linked";
  if (!actions.canWrite) return <span className={styles.documentProducts}>{label}</span>;
  return (
    <button
      className={styles.documentProductsButton}
      disabled={disabled}
      onClick={() => actions.open({ kind: "link", document })}
      title="Choose which products this document is about"
      type="button"
    >
      {label}
    </button>
  );
}

function ProductDialogShell({
  actions, children, title, submitLabel,
}: {
  actions: ProductActionsController;
  children: ReactNode;
  title: string;
  submitLabel: string;
}) {
  return (
    <div
      className={styles.dialogBackdrop}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) actions.close();
      }}
      role="presentation"
    >
      <section aria-label={title} aria-modal="true" className={`${styles.formDialog} clue-panel-enter`} role="dialog">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void actions.submit();
          }}
        >
          <div className={styles.formDialogHeader}>
            <h2>{title}</h2>
            <button aria-label={`Close ${title}`} className={styles.iconButton} disabled={actions.busy} onClick={actions.close} type="button">
              <BrandContextIcon name="close" size={16} />
            </button>
          </div>
          <div className={styles.formDialogBody}>
            {children}
            {actions.error ? <p className={styles.documentSaveError} role="alert">{actions.error}</p> : null}
          </div>
          <div className={styles.formDialogFooter}>
            <button className={styles.tertiaryButton} disabled={actions.busy} onClick={actions.close} type="button">Cancel</button>
            <button className={styles.primaryButton} disabled={!actions.canSubmit} type="submit">
              {actions.busy ? "Saving…" : submitLabel}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

function ProductChoices({
  actions, products, single,
}: {
  actions: ProductActionsController;
  products: BrandProduct[];
  single: boolean;
}) {
  if (!products.length) return <p className={styles.productDialogNote}>There are no other products.</p>;
  return (
    <fieldset className={styles.productChoiceList}>
      {products.map((product) => (
        <label className={styles.productChoice} key={product.productId}>
          <input
            checked={actions.selected.includes(product.productId)}
            name="product"
            onChange={() => actions.toggle(product.productId)}
            type={single ? "radio" : "checkbox"}
          />
          <span>{product.name}</span>
        </label>
      ))}
    </fieldset>
  );
}

/** Every product dialog. Exactly one is open at a time. */
export function ProductDialogs({ actions }: { actions: ProductActionsController }) {
  const dialog = actions.dialog;
  if (!dialog) return null;
  if (dialog.kind === "add") {
    return (
      <ProductDialogShell actions={actions} submitLabel="Add product" title="Add product">
        <label className={styles.formField}>
          <span>Product name</span>
          <input autoFocus maxLength={240} onChange={(event) => actions.setName(event.target.value)} value={actions.name} />
        </label>
        <label className={styles.formField}>
          <span>What it is <em>(optional)</em></span>
          <textarea maxLength={2000} onChange={(event) => actions.setDescription(event.target.value)} rows={3} value={actions.description} />
        </label>
        <p className={styles.productDialogNote}>Its page is written for you in the background and appears in this folder.</p>
      </ProductDialogShell>
    );
  }
  if (dialog.kind === "rename") {
    return (
      <ProductDialogShell actions={actions} submitLabel="Rename" title={`Rename ${dialog.product.name}`}>
        <label className={styles.formField}>
          <span>New name</span>
          <input autoFocus maxLength={240} onChange={(event) => actions.setName(event.target.value)} value={actions.name} />
        </label>
        <p className={styles.productDialogNote}>The old name is kept as another name for this product, so the agent still recognises it.</p>
      </ProductDialogShell>
    );
  }
  if (dialog.kind === "merge") {
    const others = actions.products.filter((product) => product.productId !== dialog.product.productId);
    return (
      <ProductDialogShell actions={actions} submitLabel="Merge" title={`Merge into ${dialog.product.name}`}>
        <p className={styles.productDialogNote}>
          Choose the products that are really part of {dialog.product.name}. They leave the list, their
          pages are retired, a fresh page is written for {dialog.product.name}, and every project that used
          them moves to {dialog.product.name}.
        </p>
        <ProductChoices actions={actions} products={others} single={false} />
      </ProductDialogShell>
    );
  }
  if (dialog.kind === "remove") {
    return (
      <ProductDialogShell actions={actions} submitLabel="Remove product" title={`Remove ${dialog.product.name}`}>
        <p className={styles.productDialogNote}>
          This removes {dialog.product.name} from the list and from every project that uses it. Its page is
          hidden, not deleted, and you can undo this from the product catalog.
        </p>
      </ProductDialogShell>
    );
  }
  const single = dialog.document.kind === PRODUCT_PAGE_KIND;
  return (
    <ProductDialogShell actions={actions} submitLabel="Save" title="Products for this document">
      <p className={styles.productDialogNote}>
        {single ? "A product page is about one product." : "Choose the products this document is about."}
      </p>
      <ProductChoices actions={actions} products={actions.products} single={single} />
    </ProductDialogShell>
  );
}
