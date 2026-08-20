/**
 * Minimal vitest-compatibility shim for the engine tests ported in W1.1.
 *
 * The design subsystem's editor runs vitest; this repo's frontend runs
 * node:test via `tsx --test` (established in W0.1). Rather than rewriting
 * 1,600 lines of engine tests — and losing their verbatim fidelity to the
 * source — this shim implements exactly the vitest surface those files use:
 * describe/it/afterEach, expect's matchers (+ `.not`, `rejects.toThrow`,
 * `resolves.*`, the `objectContaining`/`closeTo`/`any` asymmetric matchers),
 * and `vi` with `fn`/`spyOn`/`stubGlobal`/`unstubAllGlobals`.
 * Nothing more; extend only when a newly ported test needs it.
 */
import assert from "node:assert/strict";

export { afterEach, describe, it } from "node:test";

const OBJECT_CONTAINING = Symbol("objectContaining");
const CLOSE_TO = Symbol("closeTo");
const ANY = Symbol("any");

type ObjectContaining = { [OBJECT_CONTAINING]: Record<string, unknown> };
type CloseTo = { [CLOSE_TO]: { expected: number; numDigits: number } };
type AnyOf = { [ANY]: unknown };

function isObjectContaining(value: unknown): value is ObjectContaining {
  return typeof value === "object" && value !== null && OBJECT_CONTAINING in value;
}

function isCloseTo(value: unknown): value is CloseTo {
  return typeof value === "object" && value !== null && CLOSE_TO in value;
}

function isAny(value: unknown): value is AnyOf {
  return typeof value === "object" && value !== null && ANY in value;
}

/** Vitest `expect.any(Ctor)`: an instance of Ctor, or the matching primitive. */
function anyMatches(marker: AnyOf, actual: unknown): boolean {
  const ctor = marker[ANY];
  if (actual === null || actual === undefined) return false;
  if (ctor === String) return typeof actual === "string" || actual instanceof String;
  if (ctor === Number) return typeof actual === "number" || actual instanceof Number;
  if (ctor === Boolean) return typeof actual === "boolean" || actual instanceof Boolean;
  if (ctor === Object) return typeof actual === "object" || typeof actual === "function";
  return typeof ctor === "function" && actual instanceof (ctor as new () => unknown);
}

/** Vitest semantics: passes when |actual - expected| < 10**-numDigits / 2. */
function closeToMatches(marker: CloseTo, actual: unknown): boolean {
  const { expected, numDigits } = marker[CLOSE_TO];
  return typeof actual === "number" && Math.abs(actual - expected) < 10 ** -numDigits / 2;
}

function isSubset(expected: unknown, actual: unknown): boolean {
  if (isObjectContaining(expected)) {
    return isSubset(expected[OBJECT_CONTAINING], actual);
  }
  if (isCloseTo(expected)) {
    return closeToMatches(expected, actual);
  }
  if (isAny(expected)) {
    return anyMatches(expected, actual);
  }
  if (expected instanceof URL) {
    return String(actual) === String(expected);
  }
  if (expected === null || typeof expected !== "object") {
    try {
      assert.deepStrictEqual(actual, expected);
      return true;
    } catch {
      return false;
    }
  }
  if (Array.isArray(expected)) {
    if (!Array.isArray(actual) || actual.length !== expected.length) return false;
    return expected.every((item, index) => isSubset(item, actual[index]));
  }
  if (actual === null || typeof actual !== "object") return false;
  return Object.entries(expected as Record<string, unknown>).every(([key, value]) =>
    isSubset(value, (actual as Record<string, unknown>)[key]),
  );
}

/** Exact structural equality, except objectContaining markers match as subsets. */
function deepMatch(expected: unknown, actual: unknown): boolean {
  if (isObjectContaining(expected)) {
    return isSubset(expected[OBJECT_CONTAINING], actual);
  }
  if (isCloseTo(expected)) {
    return closeToMatches(expected, actual);
  }
  if (isAny(expected)) {
    return anyMatches(expected, actual);
  }
  if (expected instanceof URL) {
    return String(actual) === String(expected);
  }
  if (expected === null || typeof expected !== "object") {
    try {
      assert.deepStrictEqual(actual, expected);
      return true;
    } catch {
      return false;
    }
  }
  if (Array.isArray(expected)) {
    if (!Array.isArray(actual) || actual.length !== expected.length) return false;
    return expected.every((item, index) => deepMatch(item, actual[index]));
  }
  if (actual === null || typeof actual !== "object" || Array.isArray(actual)) return false;
  const expectedEntries = Object.entries(expected as Record<string, unknown>);
  if (expectedEntries.length !== Object.keys(actual as object).length) return false;
  return expectedEntries.every(([key, value]) =>
    deepMatch(value, (actual as Record<string, unknown>)[key]),
  );
}

function contains(haystack: unknown, needle: unknown): boolean {
  if (typeof haystack === "string") return haystack.includes(String(needle));
  if (Array.isArray(haystack)) {
    return haystack.some((item) => {
      try {
        assert.deepStrictEqual(item, needle);
        return true;
      } catch {
        return false;
      }
    });
  }
  throw new TypeError("toContain expects a string or array");
}

expect.objectContaining = (subset: Record<string, unknown>): ObjectContaining => ({
  [OBJECT_CONTAINING]: subset,
});

expect.closeTo = (expected: number, numDigits = 2): CloseTo => ({
  [CLOSE_TO]: { expected, numDigits },
});

expect.any = (ctor: unknown): AnyOf => ({ [ANY]: ctor });

function callsOf(actual: unknown): unknown[][] {
  const mock = (actual as { mock?: { calls: unknown[][] } }).mock;
  if (!mock) throw new TypeError("expected a vi.fn() mock");
  return mock.calls;
}

export function expect(actual: unknown) {
  return {
    toBe(expected: unknown) {
      assert.strictEqual(actual, expected);
    },
    toEqual(expected: unknown) {
      assert.ok(
        deepMatch(expected, actual),
        `expected ${JSON.stringify(actual)} to equal ${JSON.stringify(expected)}`,
      );
    },
    toContain(needle: unknown) {
      assert.ok(contains(actual, needle), `expected value to contain ${String(needle)}`);
    },
    toMatch(pattern: RegExp | string) {
      const re = typeof pattern === "string" ? new RegExp(pattern) : pattern;
      assert.match(String(actual), re);
    },
    toMatchObject(expected: unknown) {
      assert.ok(
        isSubset(expected, actual),
        `expected object to match subset ${JSON.stringify(expected)}`,
      );
    },
    toBeNull() {
      assert.strictEqual(actual, null);
    },
    toBeUndefined() {
      assert.strictEqual(actual, undefined);
    },
    toBeDefined() {
      assert.notStrictEqual(actual, undefined);
    },
    toHaveLength(length: number) {
      assert.strictEqual((actual as { length: number }).length, length);
    },
    toBeLessThanOrEqual(bound: number) {
      assert.ok(
        (actual as number) <= bound,
        `expected ${String(actual)} <= ${bound}`,
      );
    },
    toBeLessThan(bound: number) {
      assert.ok(
        (actual as number) < bound,
        `expected ${String(actual)} < ${bound}`,
      );
    },
    toBeGreaterThanOrEqual(bound: number) {
      assert.ok(
        (actual as number) >= bound,
        `expected ${String(actual)} >= ${bound}`,
      );
    },
    toHaveProperty(key: string) {
      assert.ok(
        actual !== null && typeof actual === "object" && key in (actual as object),
        `expected object to have property ${key}`,
      );
    },
    toHaveBeenCalledTimes(count: number) {
      assert.strictEqual(callsOf(actual).length, count);
    },
    toHaveBeenCalledWith(...expected: unknown[]) {
      const calls = callsOf(actual);
      assert.ok(
        calls.some(
          (call) =>
            call.length === expected.length &&
            expected.every((arg, index) => deepMatch(arg, call[index])),
        ),
        `expected a call with ${JSON.stringify(expected.map(String))}, got ${JSON.stringify(
          calls.map((call) => call.map(String)),
        )}`,
      );
    },
    /** Vitest semantics: passes when |actual - expected| < 10**-numDigits / 2. */
    toBeCloseTo(expected: number, numDigits = 2) {
      const tolerance = 10 ** -numDigits / 2;
      assert.ok(
        Math.abs((actual as number) - expected) < tolerance,
        `expected ${String(actual)} to be within ${tolerance} of ${expected}`,
      );
    },
    not: {
      toBe(expected: unknown) {
        assert.notStrictEqual(actual, expected);
      },
      toBeNull() {
        assert.notStrictEqual(actual, null);
      },
      toContain(needle: unknown) {
        assert.ok(
          !contains(actual, needle),
          `expected value NOT to contain ${String(needle)}`,
        );
      },
      toHaveProperty(key: string) {
        assert.ok(
          !(actual !== null && typeof actual === "object" && key in (actual as object)),
          `expected object NOT to have property ${key}`,
        );
      },
    },
    rejects: {
      async toThrow(message?: string) {
        await assert.rejects(
          Promise.resolve(actual as Promise<unknown>),
          message === undefined
            ? undefined
            : (error: unknown) => String((error as Error).message).includes(message),
        );
      },
    },
    resolves: {
      async toEqual(expected: unknown) {
        const resolved = await (actual as Promise<unknown>);
        assert.ok(
          deepMatch(expected, resolved),
          `expected ${JSON.stringify(resolved)} to equal ${JSON.stringify(expected)}`,
        );
      },
      async toBeNull() {
        assert.strictEqual(await (actual as Promise<unknown>), null);
      },
    },
  };
}

type AnyFn = (...args: never[]) => unknown;

export interface MockFn<T extends AnyFn = typeof fetch> {
  (...args: Parameters<T>): ReturnType<T>;
  mock: { calls: unknown[][] };
  mockResolvedValue(value: unknown): MockFn<T>;
  mockResolvedValueOnce(value: unknown): MockFn<T>;
  mockImplementation(impl: (...args: Parameters<T>) => ReturnType<T>): MockFn<T>;
  mockRestore(): void;
}

function makeMock<T extends AnyFn>(
  impl?: (...args: Parameters<T>) => ReturnType<T>,
  restore?: () => void,
): MockFn<T> {
  let implementation = impl;
  const queued: unknown[] = [];
  let resolved: unknown;
  let hasResolved = false;
  const mock: { calls: unknown[][] } = { calls: [] };
  const fn = ((...args: unknown[]) => {
    mock.calls.push(args);
    if (queued.length > 0) return Promise.resolve(queued.shift());
    if (hasResolved) return Promise.resolve(resolved);
    if (implementation) return implementation(...(args as Parameters<T>));
    throw new Error("vi.fn(): no implementation or resolved value configured");
  }) as unknown as MockFn<T>;
  fn.mock = mock;
  fn.mockResolvedValue = (value: unknown) => {
    resolved = value;
    hasResolved = true;
    return fn;
  };
  fn.mockResolvedValueOnce = (value: unknown) => {
    queued.push(value);
    return fn;
  };
  fn.mockImplementation = (next: (...args: Parameters<T>) => ReturnType<T>) => {
    implementation = next;
    return fn;
  };
  fn.mockRestore = () => restore?.();
  return fn;
}

/** Globals replaced by `vi.stubGlobal`, in replacement order. */
const stubbedGlobals: Array<{ key: string; had: boolean; previous: unknown }> = [];

export const vi = {
  fn<T extends AnyFn = typeof fetch>(
    impl?: (...args: Parameters<T>) => ReturnType<T>,
  ): MockFn<T> {
    return makeMock<T>(impl);
  },
  /** Replaces one method with a mock; `mockRestore()` puts the original back. */
  spyOn<T extends object, K extends keyof T>(target: T, key: K): MockFn<AnyFn> {
    const original = target[key];
    const spy = makeMock<AnyFn>(original as unknown as AnyFn, () => {
      (target as Record<string, unknown>)[key as string] = original;
    });
    (target as Record<string, unknown>)[key as string] = spy;
    return spy;
  },
  stubGlobal(key: string, value: unknown): void {
    const scope = globalThis as unknown as Record<string, unknown>;
    stubbedGlobals.push({ key, had: key in scope, previous: scope[key] });
    scope[key] = value;
  },
  unstubAllGlobals(): void {
    const scope = globalThis as unknown as Record<string, unknown>;
    while (stubbedGlobals.length > 0) {
      const entry = stubbedGlobals.pop();
      if (!entry) continue;
      if (entry.had) scope[entry.key] = entry.previous;
      else delete scope[entry.key];
    }
  },
};
