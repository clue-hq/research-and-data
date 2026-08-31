import { useEffect, useMemo, useRef, useState } from "react";
import { useChatTransport } from "@/features/projects/data/projects-transport";
import { lookupContactEmails } from "../../data/bulk-actions.repository";
import { ClueApiError } from "../../data/clue-api-error";
import type { AccountContactSummary } from "../../model/account-contact";
import type { ContactBulkCapabilities } from "../../model/bulk-actions";
import type { AccountTableDensity } from "../../model/account-table-view";
import {
  defaultContactColumnWidths,
  type ContactColumnKey,
} from "../../model/contact-table-view";

export function useAccountContactsController(
  accountId: string,
  initialContacts: AccountContactSummary[],
  bulkCapabilities: ContactBulkCapabilities,
) {
  const chatHandoffAvailable = useChatTransport().mode === "http";
  const [contacts, setContacts] = useState(initialContacts);
  const [search, setSearchState] = useState("");
  const [displayOpen, setDisplayOpen] = useState(false);
  const [density, setDensity] = useState<AccountTableDensity>("spacious");
  const [columnWidths, setColumnWidths] = useState(defaultContactColumnWidths);
  const [selectedContactIds, setSelectedContactIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [page, setPageState] = useState(1);
  const [pageSize, setPageSizeState] = useState(20);
  const [isBulkSubmitting, setIsBulkSubmitting] = useState(false);
  const [bulkNotice, setBulkNotice] = useState<string | null>(null);
  const bulkAttemptKey = useRef<string | null>(null);
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

  const filteredContacts = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return contacts;
    return contacts.filter((contact) =>
      [contact.name, contact.title, contact.persona, contact.roleOnCommittee.value]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(query),
    );
  }, [contacts, search]);
  const totalPages = Math.max(1, Math.ceil(filteredContacts.length / pageSize));
  const visibleContacts = useMemo(
    () => filteredContacts.slice((page - 1) * pageSize, page * pageSize),
    [filteredContacts, page, pageSize],
  );

  function clearSelection() {
    setSelectedContactIds(new Set());
    bulkAttemptKey.current = null;
  }

  function setSearch(value: string) {
    clearSelection();
    setPageState(1);
    setSearchState(value);
  }

  function setPage(value: number) {
    clearSelection();
    setPageState(Math.min(totalPages, Math.max(1, value)));
  }

  function setPageSize(value: number) {
    clearSelection();
    setPageState(1);
    setPageSizeState(value);
  }

  function toggleContact(contactId: string) {
    bulkAttemptKey.current = null;
    setSelectedContactIds((current) => {
      const next = new Set(current);
      if (next.has(contactId)) next.delete(contactId);
      else next.add(contactId);
      return next;
    });
  }

  function toggleAllVisibleContacts() {
    bulkAttemptKey.current = null;
    setSelectedContactIds((current) => {
      const allSelected =
        visibleContacts.length > 0 &&
        visibleContacts.every((contact) => current.has(contact.id));
      return allSelected
        ? new Set()
        : new Set(visibleContacts.map((contact) => contact.id));
    });
  }

  async function executeEmailLookup() {
    const selectedCount = selectedContactIds.size;
    if (!selectedCount || isBulkSubmitting) return;
    if (selectedCount > bulkCapabilities.lookupWorkEmails.maxItems) return;
    if (!window.confirm(`Look up work emails for ${selectedCount} contacts?`)) return;
    const idempotencyKey = bulkAttemptKey.current ?? crypto.randomUUID();
    bulkAttemptKey.current = idempotencyKey;
    setIsBulkSubmitting(true);
    setBulkNotice(null);
    try {
      const result = await lookupContactEmails({
        accountId,
        contactIds: [...selectedContactIds],
        idempotencyKey,
      });
      const lookupByContact = new Map(
        result.items.flatMap((item) =>
          item.emailLookup ? [[item.subjectId, item.emailLookup] as const] : [],
        ),
      );
      setContacts((current) =>
        current.map((contact) => ({
          ...contact,
          emailLookup: lookupByContact.get(contact.id) ?? contact.emailLookup,
        })),
      );
      const parts = [
        result.counts.completed ? `${result.counts.completed} started or completed` : null,
        result.counts.unchanged ? `${result.counts.unchanged} reused` : null,
        result.counts.ineligible ? `${result.counts.ineligible} ineligible` : null,
        result.counts.failed ? `${result.counts.failed} failed` : null,
      ].filter(Boolean);
      setBulkNotice(parts.join(" · "));
      clearSelection();
    } catch (error) {
      if (error instanceof ClueApiError && error.status === 401) {
        window.location.assign("/sign-in?reason=session_expired");
        return;
      }
      setBulkNotice(
        error instanceof ClueApiError && error.status === 403
          ? "You no longer have permission to look up work emails."
          : "The email lookup batch could not finish. Try again to safely resume it.",
      );
    } finally {
      setIsBulkSubmitting(false);
    }
  }

  function setColumnWidth(column: ContactColumnKey, width: number) {
    setColumnWidths((current) => ({ ...current, [column]: width }));
  }

  function resetColumnWidth(column: ContactColumnKey) {
    setColumnWidths((current) => ({
      ...current,
      [column]: defaultContactColumnWidths[column],
    }));
  }

  return [
    {
      bulkCapabilities,
      bulkNotice,
      chatHandoffAvailable,
      clearBulkNotice: () => setBulkNotice(null),
      clearSelection,
      columnWidths,
      density,
      displayOpen,
      executeEmailLookup,
      filteredCount: filteredContacts.length,
      isBulkSubmitting,
      page,
      pageSize,
      resetColumnWidth,
      search,
      selectedContactIds,
      selectionEnabled:
        bulkCapabilities.lookupWorkEmails.allowed ||
        (chatHandoffAvailable && bulkCapabilities.addToChat.allowed),
      setDensity,
      setColumnWidth,
      setDisplayOpen,
      setPage,
      setPageSize,
      setSearch,
      toggleContact,
      toggleAllVisibleContacts,
      toggleDisplay: () => setDisplayOpen((current) => !current),
      totalPages,
      visibleContacts,
    },
    displayControlsRef,
  ] as const;
}
