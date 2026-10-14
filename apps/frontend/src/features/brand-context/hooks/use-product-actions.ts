"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  addProduct,
  linkDocumentProducts,
  mergeProducts,
  removeProduct,
  renameProduct,
  undoProductChange,
} from "../data/brand-products";
import type { BrandKnowledgeDocument } from "../model/brand-context";
import type { BrandProduct, BrandProducts } from "../model/brand-knowledge";
import { PRODUCT_PAGE_KIND } from "../model/product-links";

/** The one product dialog open at a time (spec 2026-10-15 §10). */
export type ProductDialog =
  | { kind: "add" }
  | { kind: "rename"; product: BrandProduct }
  | { kind: "merge"; product: BrandProduct }
  | { kind: "remove"; product: BrandProduct }
  | { kind: "link"; document: BrandKnowledgeDocument };

export function useProductActions(products: BrandProducts | null, canWrite: boolean) {
  const router = useRouter();
  const [dialog, setDialog] = useState<ProductDialog | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const list = products?.products ?? [];

  function open(next: ProductDialog) {
    if (!canWrite) return;
    setDialog(next);
    setError(null);
    setName(next.kind === "rename" ? next.product.name : "");
    setDescription("");
    setSelected(next.kind === "link" ? [...(next.document.productIds ?? [])] : []);
  }

  function close() {
    if (busy) return;
    setDialog(null);
    setError(null);
  }

  function toggle(productId: string) {
    setSelected((current) => {
      if (dialog?.kind === "link" && dialog.document.kind === PRODUCT_PAGE_KIND) return [productId];
      return current.includes(productId)
        ? current.filter((id) => id !== productId)
        : [...current, productId];
    });
  }

  async function run(action: () => Promise<string>) {
    setBusy(true);
    setError(null);
    try {
      setNotice(await action());
      setDialog(null);
      router.refresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not change the products. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  function canSubmit(): boolean {
    if (!dialog || busy) return false;
    if (dialog.kind === "add" || dialog.kind === "rename") return name.trim().length > 0;
    if (dialog.kind === "merge") return selected.length > 0;
    if (dialog.kind === "link") {
      return dialog.document.kind !== PRODUCT_PAGE_KIND || selected.length === 1;
    }
    return true;
  }

  async function submit() {
    if (!dialog || !canSubmit()) return;
    const current = dialog;
    if (current.kind === "add") {
      await run(async () => (await addProduct({ name: name.trim(), description: description.trim() || undefined })).text);
    } else if (current.kind === "rename") {
      await run(async () => (await renameProduct(current.product.productId, name.trim())).text);
    } else if (current.kind === "merge") {
      await run(async () => (await mergeProducts({ productIds: selected, intoProductId: current.product.productId })).text);
    } else if (current.kind === "remove") {
      await run(async () => (await removeProduct(current.product.productId)).text);
    } else {
      await run(async () => {
        await linkDocumentProducts(current.document, selected);
        return "Products updated for this document";
      });
    }
  }

  async function undo(changeId: string) {
    if (!canWrite || busy) return;
    await run(async () => (await undoProductChange(changeId)).text);
  }

  return {
    available: products !== null,
    busy, canSubmit: canSubmit(), canWrite, close, description, dialog, error, name, notice, open,
    products: list, recentChanges: products?.recentChanges ?? [], selected, setDescription, setName,
    submit, toggle, undo,
  };
}

export type ProductActionsController = ReturnType<typeof useProductActions>;
