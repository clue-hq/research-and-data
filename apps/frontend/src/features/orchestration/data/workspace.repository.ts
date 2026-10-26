import { createBrowserRecordStore } from "@/features/preview/data/browser-record-store";
import { approveEmail, markReplyHandled, saveEmail, setAccountOwner, WorkspaceSchema, type EmailPatch, type WorkspaceState } from "../model/workspace";
import { createWorkspaceFixture } from "./workspace.fixture";

export interface WorkspaceRepository {
  read(): Promise<WorkspaceState>;
  updateAccountOwner(id: string, revision: number, ownerId: string): Promise<WorkspaceState>;
  saveEmail(id: string, revision: number, patch: EmailPatch): Promise<WorkspaceState>;
  approveEmail(id: string, revision: number): Promise<WorkspaceState>;
  markReplyHandled(id: string, revision: number): Promise<WorkspaceState>;
  addChatMessage(text: string): Promise<WorkspaceState>;
  subscribe(listener: () => void): () => void;
}
type Store = { read(): Promise<WorkspaceState>; transact<R>(change: (state: WorkspaceState) => { state: WorkspaceState; result: R }): Promise<R> };
const EVENT = "clue-orchestration-v2";
export function createWorkspaceRepository(store: Store = createBrowserRecordStore("clue-orchestration-preview-v2", (v) => WorkspaceSchema.parse(v), createWorkspaceFixture)): WorkspaceRepository {
  async function write(change: (state: WorkspaceState) => WorkspaceState) {
    const next = await store.transact((s) => { const state = WorkspaceSchema.parse(change(s)); return { state, result: state }; });
    if (typeof window !== "undefined") { window.dispatchEvent(new Event(EVENT)); if (typeof BroadcastChannel !== "undefined") { const channel = new BroadcastChannel(EVENT); channel.postMessage("changed"); channel.close(); } }
    return next;
  }
  return {
    read: () => store.read(),
    updateAccountOwner: (id, revision, ownerId) => write((s) => setAccountOwner(s, id, revision, ownerId)),
    saveEmail: (id, revision, patch) => write((s) => saveEmail(s, id, revision, patch)),
    approveEmail: (id, revision) => write((s) => approveEmail(s, id, revision)),
    markReplyHandled: (id, revision) => write((s) => markReplyHandled(s, id, revision)),
    addChatMessage: (text) => write((s) => {
      const input = text.trim();
      if (!input || input.length > 2000) throw new Error("Write a message of up to 2,000 characters.");
      const email = /email|reply|repl|meeting/i.test(input), gift = /gift|note|cost|approv/i.test(input);
      s.messages.push({ id: crypto.randomUUID(), role: "user", text: input, action: "none" });
      s.messages.push({ id: crypto.randomUUID(), role: "assistant", text: email ? "The prepared email view connects each recipient to their account and sender. Riley’s reply is waiting for Jamie; the other messages can be reviewed individually before scheduling. This example does not send email." : gift ? "Avery’s prepared gift, note and cost breakdown are available together. Priya’s send is held for a receiving address. Review each recipient before approving the ready mailers; no purchase is made in this preview." : "The account plan brings together the six prepared examples, including two without gifts. You can change an account owner, inspect the evidence, and open the connected assets. New research and custom generation will use the agent service when connected.", action: email ? "email" : gift ? "review" : "plan" });
      return s;
    }),
    subscribe(listener) {
      if (typeof window === "undefined") return () => {};
      window.addEventListener(EVENT, listener);
      const channel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(EVENT);
      if (channel) channel.onmessage = listener;
      return () => { window.removeEventListener(EVENT, listener); channel?.close(); };
    },
  };
}
