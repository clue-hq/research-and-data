import { StateSchema, type DirectMailState } from "../model/direct-mail";
import { createDirectMailFixture } from "./direct-mail.fixture";
import { createBrowserRecordStore } from "@/features/preview/data/browser-record-store";

export interface DirectMailStore {
  read(): Promise<DirectMailState>;
  transact<T>(change: (state: DirectMailState) => { state: DirectMailState; result: T }): Promise<T>;
}

/** One atomic workspace record: concurrent tabs cannot approve an outdated draft. */
export function createBrowserDirectMailStore(seed = createDirectMailFixture, name = "clue-direct-mail-preview-v1", parse: (value:unknown) => DirectMailState = (value) => StateSchema.parse(value)): DirectMailStore {
  return createBrowserRecordStore(name, parse, seed);
}
