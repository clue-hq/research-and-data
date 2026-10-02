#!/usr/bin/env node
// Separate Next processes; the existing authenticated backend still owns tenancy.
// Usage: node scripts/local-workspace-instances.mjs run|status|stop /path/to/instances.json
import { spawn, execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync, openSync, closeSync, existsSync } from "node:fs";
import { createServer } from "node:net";
import { dirname, resolve } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const script = fileURLToPath(import.meta.url);
const frontend = resolve(dirname(script), "..");
const [command, manifestArg] = process.argv.slice(2);
if (!["run", "status", "stop"].includes(command) || !manifestArg) {
  throw new Error("Usage: local-workspace-instances.mjs run|status|stop <instances.json>");
}
const manifestPath = resolve(manifestArg);
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
if (!Array.isArray(manifest.instances) || !manifest.instances.length) throw new Error("instances must be a nonempty array");
const ports = new Set();
for (const row of manifest.instances) {
  if (!Number.isInteger(row.port) || row.port < 1024 || row.port > 65535 || ports.has(row.port)) throw new Error("Instance ports must be unique integers between 1024 and 65535");
  if (typeof row.name !== "string" || !row.name.trim() || !/^ws_[a-zA-Z0-9_]+$/.test(row.workspaceId)) throw new Error("Each instance needs a name and an existing workspaceId");
  ports.add(row.port);
}
const manifestHash = createHash("sha256").update(JSON.stringify(manifest)).digest("hex");
const statePath = resolve(dirname(manifestPath), "runtime.json");
const state = existsSync(statePath) ? JSON.parse(readFileSync(statePath, "utf8")) : null;
function alive(pid) {
  try { process.kill(pid, 0); return true; } catch { return false; }
}
function ownsManager() {
  if (!state || !alive(state.pid)) return false;
  const processCommand = execFileSync("/bin/ps", ["-p", String(state.pid), "-o", "command="], { encoding: "utf8" });
  return processCommand.includes(script) && processCommand.includes(manifestPath);
}
if (command === "status") {
  console.log(ownsManager() ? "Instance manager is running" : "Instance manager is stopped");
  for (const row of manifest.instances) console.log(`${row.name}: http://localhost:${row.port}`);
  process.exit(0);
}
if (command === "stop") {
  if (ownsManager()) { process.kill(state.pid, "SIGTERM"); console.log("Stopping recorded local instances"); }
  else console.log("No owned instance manager is running");
  process.exit(0);
}
if (ownsManager()) throw new Error("The recorded instance manager is already running; stop it before restarting");

// Refuse conflicts before starting any instance. Bind only IPv4 loopback.
for (const port of ports) {
  await new Promise((done, fail) => {
    const probe = createServer();
    probe.once("error", fail);
    probe.listen(port, "127.0.0.1", () => probe.close(done));
  });
}
const require = createRequire(import.meta.url);
require("@next/env").loadEnvConfig(frontend, true, { info() {}, error: console.error });
if (process.env.CLUE_AUTH_ENABLED !== "true") throw new Error("Instances require the existing authenticated frontend configuration");
const authorized = [...new Set([
  ...(process.env.CLUE_AUTH_CLERK_AUTHORIZED_PARTIES || "").split(",").filter(Boolean),
  ...manifest.instances.map((row) => `http://localhost:${row.port}`),
])].join(",");
const logDir = resolve(dirname(manifestPath), "logs");
mkdirSync(logDir, { recursive: true, mode: 0o700 });
const children = [];
let stopping = false;
function stop(exitCode = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (alive(child.pid)) { try { process.kill(-child.pid, "SIGTERM"); } catch {} }
  }
  setTimeout(() => {
    for (const child of children) {
      if (alive(child.pid)) { try { process.kill(-child.pid, "SIGKILL"); } catch {} }
    }
    process.exit(exitCode);
  }, 4000);
}
process.once("SIGTERM", () => stop());
process.once("SIGINT", () => stop());
for (const row of manifest.instances) {
  // Next updates its TS include paths during startup. Give each compiler its own
  // config so simultaneous dev servers never rewrite the shared source config.
  writeFileSync(resolve(frontend, `tsconfig.local-${row.port}.json`), JSON.stringify({
    extends: "./tsconfig.json",
    include: ["next-env.d.ts", "src/**/*.ts", "src/**/*.tsx", `.next-local-${row.port}/dev/types/**/*.ts`, `.next-local-${row.port}/types/**/*.ts`],
    exclude: ["node_modules"],
  }, null, 2));
  const log = openSync(resolve(logDir, `${row.port}.log`), "a", 0o600);
  const child = spawn(process.execPath, [resolve(frontend, "node_modules/next/dist/bin/next"), "dev", "--hostname", "127.0.0.1", "--port", String(row.port)], {
    cwd: frontend,
    detached: true,
    stdio: ["ignore", log, log],
    env: {
      ...process.env,
      NODE_ENV: "development",
      CLUE_APP_ORIGIN: `http://localhost:${row.port}`,
      CLUE_AUTH_CLERK_AUTHORIZED_PARTIES: authorized,
      CLUE_LOCAL_WORKSPACE_ID: row.workspaceId,
      CLUE_LOCAL_WORKSPACE_NAME: row.name,
    },
  });
  closeSync(log);
  child.on("error", (error) => { console.error(`${row.name}: ${error.message}`); stop(1); });
  child.on("exit", (code) => { if (!stopping) { console.error(`${row.name} exited (${code}); inspect ${logDir}`); stop(1); } });
  children.push(child);
  console.log(`${row.name}: http://localhost:${row.port} — pinned to ${row.workspaceId}`);
}
writeFileSync(statePath, JSON.stringify({ pid: process.pid, manifestHash, instances: manifest.instances.map((row, i) => ({ ...row, pid: children[i].pid })) }, null, 2), { mode: 0o600 });
