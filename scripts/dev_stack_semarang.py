#!/usr/bin/env python3
"""Semarang-only launcher: .venv/bin/python scripts/dev_stack_semarang.py up|down|status.

Postgres is shared infrastructure; only clue_semarang is used. Redis, application
processes and logs belong to this checkout. Agent scratch uses a Semarang-only
external root as required by WorkspaceRootPolicy. Never uses pkill.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
STATE = RUNTIME / "processes.json"
DESIGN = ROOT / "subsystems/clue-design"
PYTHON = str(ROOT / ".venv/bin/python")
REDIS = "clue-redis-semarang"


def process_stamp(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True)
    return result.stdout.strip()


def owned(record):
    if not record.get("stamp") or process_stamp(record["pid"]) != record["stamp"]:
        return False
    cwd = subprocess.run(
        ["lsof", "-a", "-p", str(record["pid"]), "-d", "cwd", "-Fn"],
        capture_output=True,
        text=True,
    )
    return f"n{record['cwd']}" in cwd.stdout.splitlines()


def read_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(state):
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(STATE)


def config():
    env = {**os.environ, **{k: v for k, v in dotenv_values(ROOT / ".env").items() if v is not None}}
    if ROOT.name != "semarang" or urlsplit(env["CLUE_DATABASE_URL"]).path != "/clue_semarang":
        raise SystemExit("Refusing to launch outside Semarang or against a different database.")
    if env.get("CLUE_REDIS_URL") != "redis://127.0.0.1:56379/0":
        raise SystemExit("Semarang requires its dedicated Redis on 56379/0.")
    scratch = Path(env["CLUE_AGENT_WORKSPACE_ROOT"])
    if (
        scratch != Path("/private/tmp/clue-agent-workspaces-semarang")
        or scratch.resolve() != scratch
    ):
        raise SystemExit("Semarang requires its dedicated external agent scratch root.")
    for key in (
        "CLUE_STORAGE_FS_ROOT",
        "CLUE_ARV2_RAW_ROOT",
        "CLUE_TRIAL_ROOT",
        "LUMEN_CORE_HELPER",
        "LUMEN_FONT_LIBRARY_MANIFEST_PATH",
        "LUMEN_AGENT_WORKSPACE_ROOT",
        "LUMEN_AGENT_TRACE_DIR",
    ):
        path = Path(env[key])
        if not path.is_absolute() or not path.resolve().is_relative_to(ROOT):
            raise SystemExit(f"{key} must resolve inside {ROOT}.")
    if not Path(env["LUMEN_CORE_HELPER"]).is_file():
        raise SystemExit("Build Semarang's lumen-api-helper before starting the stack.")
    env.update(
        PYTHONPATH=os.pathsep.join(
            map(str, (DESIGN, DESIGN / "apps/api", DESIGN / "apps/agent_runtime"))
        ),
        PYTHONUNBUFFERED="1",
        TMPDIR=str(RUNTIME / "tmp") + "/",
        CLUE_DESIGN_API_BASE_URL="http://127.0.0.1:8071",
        LUMEN_API_ORIGIN="http://127.0.0.1:8071",
        LUMEN_EMBEDDED_FLEET_WORKER="0",
    )
    return env


def ensure_redis():
    found = subprocess.run(["docker", "inspect", REDIS], capture_output=True, text=True)
    if found.returncode == 0:
        container = json.loads(found.stdout)[0]
        mounts = container["Mounts"]
        ports = container["HostConfig"]["PortBindings"].get("6379/tcp", [])
        if not any(
            m["Source"] == str(RUNTIME / "redis") and m["Destination"] == "/data" for m in mounts
        ):
            raise SystemExit("Existing Semarang Redis has a different data mount.")
        if ports != [{"HostIp": "127.0.0.1", "HostPort": "56379"}]:
            raise SystemExit("Existing Semarang Redis has different ports.")
        subprocess.run(["docker", "start", REDIS], check=True, stdout=subprocess.DEVNULL)
    else:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                REDIS,
                "--label",
                f"clue.worktree={ROOT}",
                "-p",
                "127.0.0.1:56379:6379",
                "-v",
                f"{RUNTIME / 'redis'}:/data",
                "redis:7-alpine",
                "redis-server",
                "--appendonly",
                "yes",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )


def start():
    env = config()
    for directory in ("logs", "tmp", "redis"):
        (RUNTIME / directory).mkdir(parents=True, exist_ok=True)
    state = read_state()
    frontend_env = {
        **env,
        **{
            k: v
            for k, v in dotenv_values(ROOT / "apps/frontend/.env.local").items()
            if v is not None
        },
    }
    frontend_env.update(
        CLUE_API_BASE_URL="http://127.0.0.1:8070",
        LUMEN_API_BASE_URL="http://127.0.0.1:8071",
        CLUE_APP_ORIGIN="http://localhost:3040",
    )
    specs = [
        (
            "platform-api",
            ROOT,
            [
                PYTHON,
                "-m",
                "uvicorn",
                "clue_api.projections_main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8070",
            ],
            env,
            8070,
        ),
        (
            "design-api",
            DESIGN,
            [
                PYTHON,
                "-m",
                "uvicorn",
                "lumen_api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8071",
            ],
            env,
            8071,
        ),
        (
            "frontend",
            ROOT / "apps/frontend",
            [
                shutil.which("node"),
                str(ROOT / "apps/frontend/node_modules/next/dist/bin/next"),
                "dev",
                "--hostname",
                "127.0.0.1",
                "--port",
                "3040",
            ],
            frontend_env,
            3040,
        ),
    ]
    specs.extend(
        (f"worker-{i}", ROOT, [PYTHON, "-m", "clue_api.fleet_main"], env, None) for i in range(1, 5)
    )
    # Check all app ports before starting anything. An untracked listener is never stopped.
    for name, _, _, _, port in specs:
        if port and not owned(state.get(name, {})):
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    raise SystemExit(
                        f"Port {port} is occupied by an untracked process; leaving it alone."
                    )
    ensure_redis()
    for name, cwd, command, process_env, _ in specs:
        if owned(state.get(name, {})):
            continue
        with (RUNTIME / "logs" / f"{name}.log").open("ab") as log:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=process_env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        state[name] = {"pid": process.pid, "stamp": process_stamp(process.pid), "cwd": str(cwd)}
        save_state(state)
        # Registry seeding currently needs serialized worker starts.
        time.sleep(6 if name.startswith("worker-") else 1)
        if process.poll() is not None:
            raise SystemExit(f"{name} exited; inspect {RUNTIME / 'logs' / (name + '.log')}.")
    status()
    print("App: http://localhost:3040/brand-context")


def status():
    for name, record in read_state().items():
        print(f"{name}: {'UP' if owned(record) else 'DOWN'} (PID {record['pid']})")


def stop():
    for name, record in read_state().items():
        if owned(record) and os.getpgid(record["pid"]) == record["pid"]:
            os.killpg(record["pid"], signal.SIGTERM)
            print(f"Stopping {name} (PID {record['pid']})")
    print("Redis and the shared Postgres container are left running.")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) == 2 else "status"
    if action not in {"up", "down", "status"}:
        raise SystemExit("Usage: .venv/bin/python scripts/dev_stack_semarang.py up|down|status")
    {"up": start, "down": stop, "status": status}[action]()
