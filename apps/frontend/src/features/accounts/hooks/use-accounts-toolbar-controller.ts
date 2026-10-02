"use client";

import {
  type FormEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import type {
  AccountSort,
} from "../model/account-table-view";
import {
  defaultAccountFilterOperator,
  type AccountFilterField,
  type AccountFilterRule,
} from "../model/account-query";

export type OpenAccountsPanel = "columns" | "filter" | "new" | "sort" | null;
type SortField = "default" | "name" | "project";

export function useAccountsSortController(
  sort: AccountSort,
  onSortChange: (sort: AccountSort) => void,
) {
  const [sortField, setSortField] = useState<SortField>(
    sort === "default"
      ? "default"
      : sort.startsWith("project")
        ? "project"
        : "name",
  );
  const descending = sort.endsWith("-desc");

  function chooseField(field: SortField) {
    setSortField(field);
    onSortChange(
      field === "default"
        ? "default"
        : field === "project"
          ? "project-asc"
          : "name-asc",
    );
  }

  function chooseAscending() {
    if (sortField === "project") onSortChange("project-asc");
    if (sortField === "name") onSortChange("name-asc");
  }

  function chooseDescending() {
    if (sortField === "project") onSortChange("project-desc");
    if (sortField === "name") onSortChange("name-desc");
  }

  return {
    chooseAscending,
    chooseDescending,
    chooseField,
    descending,
    sortField,
  };
}

export function useAccountsFilterController(
  filters: AccountFilterRule[],
  onFiltersChange: (filters: AccountFilterRule[]) => void,
) {
  const nextRuleId = useRef(filters.length + 1);

  function addRule() {
    nextRuleId.current += 1;
    onFiltersChange([
      ...filters,
      {
        field: "project",
        id: `account-filter-${nextRuleId.current}`,
        join: "and",
        operator: "is",
        value: "",
      },
    ]);
  }

  function clearRules() {
    onFiltersChange([
      {
        field: "name",
        id: "account-filter-1",
        join: "and",
        operator: "contains",
        value: "",
      },
    ]);
  }

  function removeRule(ruleId: string) {
    const remaining = filters.filter((rule) => rule.id !== ruleId);
    nextRuleId.current += 1;
    onFiltersChange(
      remaining.length
        ? remaining
        : [
            {
              field: "name",
              id: `account-filter-${nextRuleId.current}`,
              join: "and",
              operator: "contains",
              value: "",
            },
          ],
    );
  }

  function updateRule(
    ruleId: string,
    update: Partial<AccountFilterRule>,
  ) {
    onFiltersChange(
      filters.map((rule) =>
        rule.id === ruleId ? { ...rule, ...update } : rule,
      ),
    );
  }

  function updateField(ruleId: string, field: AccountFilterField) {
    updateRule(ruleId, {
      field,
      operator: defaultAccountFilterOperator(field),
      value: "",
    });
  }

  return {
    activeRuleCount: filters.filter((rule) => rule.value.trim()).length,
    addRule,
    clearRules,
    removeRule,
    updateField,
    updateRule,
  };
}

export function useAccountsToolbarController(
  onCreateAccount: (name: string, websiteUrl: string) => void,
) {
  const [openPanel, setOpenPanel] = useState<OpenAccountsPanel>(null);
  const [newAccountName, setNewAccountName] = useState("");
  const [newAccountWebsite, setNewAccountWebsite] = useState("");
  const controlsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpenPanel(null);
    }

    function closeOnOutsideClick(event: MouseEvent) {
      const target = event.target as Element;
      if (
        openPanel !== "new" &&
        controlsRef.current &&
        !controlsRef.current.contains(target) &&
        !target.closest("[data-clue-account-filter-select]")
      ) {
        setOpenPanel(null);
      }
    }

    document.addEventListener("keydown", closeOnEscape);
    document.addEventListener("mousedown", closeOnOutsideClick);

    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.removeEventListener("mousedown", closeOnOutsideClick);
    };
  }, [openPanel]);

  function togglePanel(panel: Exclude<OpenAccountsPanel, null>) {
    setOpenPanel((current) => (current === panel ? null : panel));
  }

  function closePanel() {
    setOpenPanel(null);
  }

  function submitNewAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const name = newAccountName.trim();
    const rawWebsite = newAccountWebsite.trim();
    if (!name || !rawWebsite) return;

    const websiteUrl = /^https?:\/\//i.test(rawWebsite)
      ? rawWebsite
      : `https://${rawWebsite}`;

    onCreateAccount(name, websiteUrl);
    setNewAccountName("");
    setNewAccountWebsite("");
    closePanel();
  }

  return {
    closePanel,
    controlsRef,
    newAccountName,
    newAccountWebsite,
    openPanel,
    setNewAccountName,
    setNewAccountWebsite,
    submitNewAccount,
    togglePanel,
  };
}
