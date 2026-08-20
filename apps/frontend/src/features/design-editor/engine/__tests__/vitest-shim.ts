/**
 * Minimal vitest-compatibility shim for the engine tests ported in W1.1.
 *
 * The design subsystem's editor runs vitest; this repo's frontend runs
 * node:test via `tsx --test` (established in W0.1). Rather than rewriting
 * 1,600 lines of engine tests — and losing their verbatim fidelity to the
 * source — this shim implements exactly the vitest surface those files use:
 * describe/it, expect with nine matchers (+ `.not` for toBeNull/toContain,
 * `rejects.toThrow`), and `vi.fn` with `.mock.calls`/`.mockResolvedValue`.
 * Nothing more; extend only when a newly ported test needs it.
 */
import assert from "node:assert/strict";

export { afterEach, describe, it } from "node:test";

const OBJECT_CONTAINING = Symbol("objectContaining");
const CLOSE_TO = Symbol("closeTo");

type ObjectContaining = { [OBJECT_CONTAINING]: Record<string, unknown> };
type CloseTo = { [CLOSE_TO]: { expected: number; numDigits: number } };

function isObjectContaining(value: unknown): value is ObjectContaining {
  return typeof value === "object" && value !== null && OBJECT_CONTAINING in value;
}

function isCloseTo(value: unknown): value is CloseTo {
  return typeof value === "object" && value !== null && CLOSE_TO in value;
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
  };
}

interface MockedFetch {
  (...args: Parameters<typeof fetch>): ReturnType<typeof fetch>;
  mock: { calls: unknown[][] };
  mockResolvedValue(value: Response): MockedFetch;
}

export const vi = {
  fn<T = typeof fetch>(): T extends typeof fetch ? MockedFetch : never {
    let resolved: Response | undefined;
    const mock: { calls: unknown[][] } = { calls: [] };
    const fn = ((...args: unknown[]) => {
      mock.calls.push(args);
      if (resolved === undefined) {
        throw new Error("vi.fn(): no mockResolvedValue configured");
      }
      return Promise.resolve(resolved);
    }) as unknown as MockedFetch;
    fn.mock = mock;
    fn.mockResolvedValue = (value: Response) => {
      resolved = value;
      return fn;
    };
    return fn as T extends typeof fetch ? MockedFetch : never;
  },
};
