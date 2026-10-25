import { spawn } from "node:child_process";
import { createRequire } from "node:module";

const args = process.argv.slice(2);
const port = args.length === 0 ? "5000" : args.length === 2 && args[0] === "--port" ? args[1] : "";
if (!/^5\d{3}$/.test(port)) throw new Error("Use npm run dev:preview -- --port <5000–5999>.");
const require = createRequire(import.meta.url);
const child = spawn(process.execPath, [require.resolve("next/dist/bin/next"), "dev", "--hostname", "localhost", "--port", port], {
  stdio: "inherit",
  env: {
    ...process.env, NODE_ENV: "development", CLUE_FRONTEND_PREVIEW_MODE: "true",
    CLUE_AUTH_ENABLED: "false", CLUE_ACCOUNTS_FIXTURE_MODE: "true",
    CLUE_API_BASE_URL: "", CLUE_PROJECTS_API_BASE_URL: "", LUMEN_API_BASE_URL: "",
    NEXT_PUBLIC_CLUE_API_BASE_URL: "", CLUE_LOCAL_WORKSPACE_ID: "", CLUE_LOCAL_WORKSPACE_NAME: "",
    CLUE_APP_ORIGIN: `http://localhost:${port}`,
  },
});
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
child.on("exit", (code) => process.exit(code ?? 0));
