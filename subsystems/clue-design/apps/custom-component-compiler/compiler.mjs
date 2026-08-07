#!/usr/bin/env node

import { compileComponent } from "./src/compiler.mjs";
import {
  COMPILER_VERSION,
  PROTOCOL_VERSION,
  diagnostic,
} from "./src/contracts.mjs";

const MAX_PROTOCOL_BYTES = 2 * 1024 * 1024;

async function readInput() {
  const chunks = [];
  let total = 0;
  for await (const chunk of process.stdin) {
    total += chunk.length;
    if (total > MAX_PROTOCOL_BYTES) {
      throw new Error(`compiler request exceeds ${MAX_PROTOCOL_BYTES} bytes`);
    }
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

try {
  const input = await readInput();
  const output = await compileComponent(input);
  process.stdout.write(`${JSON.stringify(output)}\n`);
} catch (error) {
  process.stdout.write(
    `${JSON.stringify({
      protocol_version: PROTOCOL_VERSION,
      compiler_version: COMPILER_VERSION,
      status: "transient_error",
      diagnostics: [
        diagnostic({
          code: "CCI0001",
          category: "infrastructure",
          message: error instanceof Error ? error.message : String(error),
        }),
      ],
    })}\n`,
  );
  process.exitCode = 2;
}
