import { useEffect, useMemo, useRef, useState } from "react";
import type { AccountContactSummary } from "../../model/account-contact";
import type { AccountTableDensity } from "../../model/account-table-view";
import {
  defaultContactColumnWidths,
  type ContactColumnKey,
} from "../../model/contact-table-view";

export function useAccountContactsController(
  contacts: AccountContactSummary[],
) {
  const [search, setSearch] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [displayOpen, setDisplayOpen] = useState(false);
  const [density, setDensity] =
    useState<AccountTableDensity>("comfortable");
  const [columnWidths, setColumnWidths] = useState(
    defaultContactColumnWidths,
  );
  const displayControlsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setDisplayOpen(false);
    }

    function closeOnOutsideClick(event: MouseEvent) {
      if (
        displayControlsRef.current &&
        !displayControlsRef.current.contains(event.target as Node)
      ) {
        setDisplayOpen(false);
      }
    }

    document.addEventListener("keydown", closeOnEscape);
    document.addEventListener("mousedown", closeOnOutsideClick);

    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.removeEventListener("mousedown", closeOnOutsideClick);
    };
  }, []);

  const visibleContacts = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return contacts;

    return contacts.filter((contact) =>
      `${contact.name} ${contact.title} ${contact.persona}`
        .toLowerCase()
        .includes(query),
    );
  }, [contacts, search]);

  function setColumnWidth(column: ContactColumnKey, width: number) {
    setColumnWidths((current) => ({
      ...current,
      [column]: width,
    }));
  }

  function resetColumnWidth(column: ContactColumnKey) {
    setColumnWidths((current) => ({
      ...current,
      [column]: defaultContactColumnWidths[column],
    }));
  }

  return [
    {
      closePreview: () => setPreviewOpen(false),
      columnWidths,
      density,
      displayOpen,
      openPreview: () => setPreviewOpen(true),
      previewOpen,
      resetColumnWidth,
      search,
      setDensity,
      setColumnWidth,
      setDisplayOpen,
      setSearch,
      toggleDisplay: () => setDisplayOpen((current) => !current),
      visibleContacts,
    },
    displayControlsRef,
  ] as const;
}
