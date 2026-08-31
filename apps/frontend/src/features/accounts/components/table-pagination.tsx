"use client";

import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { useRef } from "react";
import readability from "./account-readability.module.css";

export const TABLE_PAGE_SIZE_OPTIONS = [10, 20, 30, 50, 75, 100] as const;

export function TablePagination({
  currentCount,
  isLoading,
  onPageChange,
  onPageSizeChange,
  page,
  pageSize,
  summary,
  totalItems,
  totalPages,
}: {
  currentCount: number;
  isLoading: boolean;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
  page: number;
  pageSize: number;
  summary?: string;
  totalItems: number;
  totalPages: number;
}) {
  const pageInput = useRef<HTMLInputElement>(null);

  function commitAuthoredPage() {
    const input = pageInput.current;
    if (!input) return;
    const parsed = Number(input.value);
    if (!Number.isInteger(parsed)) {
      input.value = String(page);
      return;
    }
    const bounded = Math.min(totalPages, Math.max(1, parsed));
    input.value = String(bounded);
    if (bounded !== page) onPageChange(bounded);
  }

  const firstItem = totalItems === 0 ? 0 : (page - 1) * pageSize + 1;
  const lastItem = totalItems === 0 ? 0 : firstItem + currentCount - 1;

  return (
    <div
      aria-label="Table pagination"
      className={`${readability.uiRegular} flex h-[var(--clue-ds-product-dimension-sidebar-profile-height)] shrink-0 flex-nowrap items-center justify-between gap-3 border-t-[0.5px] border-[var(--clue-border-table)] px-6`}
    >
      <span className="text-[var(--clue-content-subtle)]">
        {summary ?? `Showing ${firstItem}–${lastItem} of ${totalItems}`}
      </span>

      <div className="flex items-center gap-2" aria-label="Page navigation">
        <span aria-label="First page">1</span>
        <button
          aria-label="Previous page"
          className="flex size-7 items-center justify-center rounded-md border-[0.5px] border-[var(--clue-border-neutral)] hover:bg-[var(--clue-background-hover)] disabled:cursor-not-allowed disabled:opacity-40"
          disabled={isLoading || page <= 1}
          onClick={() => onPageChange(page - 1)}
          type="button"
        >
          <ChevronLeftIcon aria-hidden="true" size={14} strokeWidth={1.5} />
        </button>
        <input
          aria-label="Current page"
          className="h-7 w-14 rounded-md border-[0.5px] border-[var(--clue-border-input)] bg-white px-2 text-center outline-none focus:border-[var(--clue-content-neutral)]"
          defaultValue={page}
          inputMode="numeric"
          max={totalPages}
          min={1}
          onBlur={commitAuthoredPage}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
          }}
          key={page}
          ref={pageInput}
          type="number"
        />
        <button
          aria-label="Next page"
          className="flex size-7 items-center justify-center rounded-md border-[0.5px] border-[var(--clue-border-neutral)] hover:bg-[var(--clue-background-hover)] disabled:cursor-not-allowed disabled:opacity-40"
          disabled={isLoading || page >= totalPages}
          onClick={() => onPageChange(page + 1)}
          type="button"
        >
          <ChevronRightIcon aria-hidden="true" size={14} strokeWidth={1.5} />
        </button>
        <span aria-label="Last page">{totalPages}</span>
      </div>

      <label className="flex items-center gap-2 text-[var(--clue-content-subtle)]">
        <span>Show max rows</span>
        <select
          aria-label="Maximum rows per page"
          className="h-7 rounded-md border-[0.5px] border-[var(--clue-border-input)] bg-white px-2 text-[var(--clue-content-neutral)] outline-none"
          disabled={isLoading}
          onChange={(event) => onPageSizeChange(Number(event.target.value))}
          value={pageSize}
        >
          {TABLE_PAGE_SIZE_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
        <span>per page</span>
      </label>
    </div>
  );
}
