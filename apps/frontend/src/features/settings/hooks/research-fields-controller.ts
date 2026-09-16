import { ClueApiError } from "@/features/accounts/data/clue-api-error";
import {
  ResearchFieldInputSchema,
  type ResearchField,
  type ResearchFields,
  type ResearchFieldAttribute,
} from "../model/research-fields";
import type * as settingsActions from "../data/settings.actions";

type Actions = Pick<typeof settingsActions,
  "createSettingsResearchField" | "patchSettingsResearchField" | "retireSettingsResearchField">;
type Snapshot = {
  rows: ResearchField[];
  creating: boolean;
  pending: ReadonlySet<string>;
  createError: { message: string; field?: ResearchFieldAttribute } | null;
};

/** One mounted workspace/entity scope. Late responses cannot notify or mutate a new scope. */
export function createResearchFieldsController(
  initial: ResearchFields,
  canManage: boolean,
  actions: Actions,
  notify: (message: string, error?: boolean) => void,
) {
  let snapshot: Snapshot = { rows: initial.rows, creating: false, pending: new Set(), createError: null };
  let epoch = 0;
  let active = true;
  const listeners = new Set<() => void>();
  const publish = (patch: Partial<Snapshot>) => {
    snapshot = { ...snapshot, ...patch };
    listeners.forEach(listener => listener());
  };
  const current = (stamp: number) => active && stamp === epoch;
  const setPending = (operation: string, pending: boolean) => {
    const next = new Set(snapshot.pending);
    if (pending) next.add(operation); else next.delete(operation);
    publish({ pending: next });
  };
  const isPending = (key: string) => [...snapshot.pending].some(operation => operation.startsWith(`${key}:`));
  const writable = (key: string) => canManage && active && snapshot.rows.some(row => row.key === key && row.origin === "workspace");
  return {
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    getSnapshot: () => snapshot,
    activate() { active = true; },
    deactivate() { active = false; epoch++; },
    isPending,
    clearCreateError() { publish({ createError: null }); },
    async create(label: string, description: string) {
      if (!active || !canManage || snapshot.creating) return false;
      const parsed = ResearchFieldInputSchema.safeParse({ label, description });
      if (!parsed.success) {
        const issue = parsed.error.issues[0];
        publish({ createError: { message: issue.message, field: issue.path[0] as ResearchFieldAttribute } });
        return false;
      }
      const stamp = epoch;
      publish({ creating: true, createError: null });
      try {
        const row = await actions.createSettingsResearchField({ entity: initial.entity, ...parsed.data });
        if (!current(stamp)) return false;
        publish({ rows: [...snapshot.rows, row] });
        notify("Field created");
        return true;
      } catch (error) {
        if (current(stamp)) publish({ createError: {
          message: error instanceof Error ? error.message : "The field could not be created.",
          field: error instanceof ClueApiError && ["KEY_TAKEN", "LABEL_INVALID"].includes(error.code) ? "label" : undefined,
        } });
        return false;
      } finally {
        if (current(stamp)) publish({ creating: false });
      }
    },
    async update(key: string, attribute: ResearchFieldAttribute, value: string) {
      if (!writable(key)) throw new Error("This field is read-only. Reload to check your access.");
      const operation = `${key}:${attribute}`;
      if (snapshot.pending.has(operation) || snapshot.pending.has(`${key}:retire`)) throw new Error("This field is still saving.");
      const parsed = ResearchFieldInputSchema.shape[attribute].safeParse(value);
      if (!parsed.success) throw new Error(parsed.error.issues[0].message);
      const trimmed = parsed.data;
      const stamp = epoch;
      setPending(operation, true);
      try {
        const updated = await actions.patchSettingsResearchField(key, { [attribute]: trimmed });
        if (current(stamp)) publish({
          // A disjoint PATCH response may contain the previous value of the other attribute.
          rows: snapshot.rows.map(row => row.key === key ? { ...row, [attribute]: updated[attribute] } : row),
        });
        return updated[attribute];
      } finally {
        if (current(stamp)) setPending(operation, false);
      }
    },
    async retire(key: string) {
      if (!writable(key) || isPending(key)) return false;
      const stamp = epoch;
      setPending(`${key}:retire`, true);
      try {
        await actions.retireSettingsResearchField(key);
        if (!current(stamp)) return false;
        publish({ rows: snapshot.rows.filter(row => row.key !== key) });
        notify("Field retired");
        return true;
      } catch (error) {
        if (current(stamp)) notify(error instanceof Error ? error.message : "The field could not be retired.", true);
        return false;
      } finally {
        if (current(stamp)) setPending(`${key}:retire`, false);
      }
    },
  };
}
export type ResearchFieldsController = ReturnType<typeof createResearchFieldsController>;
