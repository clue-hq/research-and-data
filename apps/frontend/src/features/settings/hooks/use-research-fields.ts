"use client";
import { useEffect, useRef, useState, useSyncExternalStore, type FormEvent } from "react";
import { useConfirmation } from "@/components/ui/confirmation-card";
import * as actions from "../data/settings.actions";
import type { ResearchField, ResearchFieldAttribute, ResearchFields } from "../model/research-fields";
import { createResearchFieldsController, type ResearchFieldsController } from "./research-fields-controller";
import { useAutosaveField } from "./use-autosave-field";

export function useResearchFields(initial: ResearchFields, canManage: boolean) {
  const notify = useConfirmation();
  const [controller] = useState(() => createResearchFieldsController(initial, canManage, actions, notify));
  const snapshot = useSyncExternalStore(controller.subscribe, controller.getSnapshot, controller.getSnapshot);
  useEffect(() => {
    controller.activate();
    return () => controller.deactivate();
  }, [controller]);
  const [showCreate, setShowCreate] = useState(false);
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const createButtonRef = useRef<HTMLButtonElement>(null);
  function closeCreate() {
    if (controller.getSnapshot().creating) return;
    setShowCreate(false);
    setLabel("");
    setDescription("");
    controller.clearCreateError();
    createButtonRef.current?.focus();
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (await controller.create(label, description)) closeCreate();
  }
  return {
    ...snapshot, controller, showCreate, label, description, createButtonRef, closeCreate, submit,
    openCreate: () => { controller.clearCreateError(); setShowCreate(true); },
    setLabel: (value: string) => { setLabel(value); controller.clearCreateError(); },
    setDescription: (value: string) => { setDescription(value); controller.clearCreateError(); },
  };
}

export function useResearchFieldRow(row: ResearchField, controller: ResearchFieldsController) {
  const [editing, setEditing] = useState<ResearchFieldAttribute | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmRetire, setConfirmRetire] = useState(false);
  const menuTriggerRef = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  useEffect(() => {
    if (!editing && restoreFocus.current) {
      restoreFocus.current = false;
      menuTriggerRef.current?.focus();
    }
  }, [editing]);
  const complete = (attribute: ResearchFieldAttribute, fromKeyboard: boolean) => {
    restoreFocus.current = fromKeyboard;
    setEditing(current => current === attribute ? null : current);
  };
  const label = useAutosaveField(row.label, value => controller.update(row.key, "label", value), "Field updated", {
    onComplete: fromKeyboard => complete("label", fromKeyboard), onCancel: () => complete("label", true),
  });
  const description = useAutosaveField(row.description, value => controller.update(row.key, "description", value), "Field updated", {
    multiline: true, onComplete: fromKeyboard => complete("description", fromKeyboard), onCancel: () => complete("description", true),
  });
  return {
    menuTriggerRef, editing, label, description, menuOpen, confirmRetire,
    onMenuOpenChange: (open: boolean) => { setMenuOpen(open); if (!open) setConfirmRetire(false); },
    edit: (attribute: ResearchFieldAttribute) => { setEditing(attribute); setMenuOpen(false); },
    confirm: () => setConfirmRetire(true),
    retire: async () => {
      if (await controller.retire(row.key)) setMenuOpen(false);
    },
  };
}
