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
  const [displayOpen, setDisplayOpen] = useState(false);
  const [density, setDensity] =
    useState<AccountTableDensity>("spacious");
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

    // Name and title are both nullable on the wire; an absent field simply
    // contributes nothing to the haystack.
    return contacts.filter((contact) =>
      [contact.name, contact.title, contact.persona, contact.roleOnCommittee.value]
        .filter(Boolean)
        .join(" ")
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
      columnWidths,
      density,
      displayOpen,
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
