import assert from "node:assert/strict";
import test from "node:test";
import {
  isAuthenticationEnabled,
  requireAuthenticationConfiguration,
} from "./config";

test("authentication remains an explicit opt-in before B5", () => {
  const previous = process.env.CLUE_AUTH_ENABLED;
  delete process.env.CLUE_AUTH_ENABLED;
  try {
    assert.equal(isAuthenticationEnabled(), false);
    assert.doesNotThrow(requireAuthenticationConfiguration);
  } finally {
    if (previous === undefined) delete process.env.CLUE_AUTH_ENABLED;
    else process.env.CLUE_AUTH_ENABLED = previous;
  }
});

test("enabled authentication refuses missing provider/API configuration", () => {
  const names = [
    "CLUE_AUTH_ENABLED",
    "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
    "CLERK_SECRET_KEY",
    "CLUE_API_BASE_URL",
  ] as const;
  const previous = Object.fromEntries(names.map((name) => [name, process.env[name]]));
  process.env.CLUE_AUTH_ENABLED = "true";
  delete process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  delete process.env.CLERK_SECRET_KEY;
  delete process.env.CLUE_API_BASE_URL;
  try {
    assert.throws(
      requireAuthenticationConfiguration,
      /NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY, CLERK_SECRET_KEY, CLUE_API_BASE_URL/,
    );
  } finally {
    for (const name of names) {
      const value = previous[name];
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
});
