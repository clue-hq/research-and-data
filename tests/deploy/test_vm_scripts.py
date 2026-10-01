"""The worker VM's backup and watchdog scripts (first deployment spec §8, §11), run for real with
stand-in ``docker`` / ``curl`` / ``free`` / ``df`` commands on PATH — no Docker, R2 or VM needed.

The stand-ins log every call to ``calls.log`` and read their behaviour from environment variables,
so each test states the situation (an empty dump, an old backup, a dead pool) and asserts what the
script did about it.
"""

from __future__ import annotations

import datetime as dt
import os
import stat
import subprocess
from pathlib import Path

import pytest

VM = Path(__file__).resolve().parents[2] / "deploy" / "vm"

FAKE_DOCKER = r"""#!/usr/bin/env python3
import os, re, sys
log = os.environ["CALLS_LOG"]
args = sys.argv[1:]
with open(log, "a") as fh:
    fh.write("docker " + " ".join(args) + "\n")
def host_work():
    for i, a in enumerate(args):
        if a == "-v" and args[i + 1].endswith(":/work"):
            return args[i + 1][: -len(":/work")]
    return None
joined = " ".join(args)
if "pg_dump" in joined:
    name = re.search(r"--file=/work/(\S+)", joined).group(1)
    with open(os.path.join(host_work(), name), "wb") as fh:
        fh.write(b"" if os.environ.get("FAKE_DUMP_EMPTY") == "1" else b"PGDMP fake custom dump")
    sys.exit(0)
if "pg_restore" in joined:
    sys.exit(1 if os.environ.get("FAKE_RESTORE_FAIL") == "1" else 0)
if "amazon/aws-cli" in joined and " s3 ls " in f" {joined} ":
    for name in os.environ.get("FAKE_BACKUPS", "").split(","):
        if name:
            print(f"2026-01-01 00:00:00      100 {name}")
    sys.exit(0)
if "compose" in args and "ps" in args:
    print("\n".join(os.environ.get("FAKE_RUNNING", "").split(",")))
    sys.exit(0)
sys.exit(0)
"""

FAKE_CURL = """#!/usr/bin/env bash
echo "curl $*" >> "$CALLS_LOG"
"""

FAKE_FREE = """#!/usr/bin/env bash
echo "              total        used        free"
echo "Mem:            100 ${FAKE_MEM_USED:-50}           0"
"""

FAKE_DF = """#!/usr/bin/env bash
echo "Use%"
echo " ${FAKE_DISK_USED:-40}%"
"""

ALL_SERVICES = "chat,design,batch1,batch2,batch3,ingestion,pgbouncer"


@pytest.fixture
def sandbox(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {
        "docker": FAKE_DOCKER,
        "curl": FAKE_CURL,
        "free": FAKE_FREE,
        "df": FAKE_DF,
    }.items():
        path = bin_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    env_file = tmp_path / "backup.env"
    env_file.write_text(
        "PGURL=postgresql://u:p@db.example:5432/railway?sslmode=require\n"
        "R2_ENDPOINT=https://acct.r2.cloudflarestorage.com\n"
        "R2_BUCKET=clue-backups\n"
        "AWS_ACCESS_KEY_ID=backup-key\n"
        "AWS_SECRET_ACCESS_KEY=backup-secret\n"
        "SENTRY_CRON_URL_BACKUP=https://sentry.example/backup\n"
        "SENTRY_CRON_URL_WATCHDOG=https://sentry.example/watchdog\n",
        encoding="utf-8",
    )
    app_env = tmp_path / "env"
    app_env.write_text(
        "CLUE_STORAGE_BACKEND=s3\n"
        "CLUE_STORAGE_S3_BUCKET=clue-prod\n"
        "CLUE_STORAGE_S3_ACCESS_KEY_ID=app-key\n",
        encoding="utf-8",
    )
    return {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CALLS_LOG": str(tmp_path / "calls.log"),
        "CLUE_BACKUP_ENV": str(env_file),
        "CLUE_ENV_FILE": str(app_env),
        "CLUE_COMPOSE_FILE": str(tmp_path / "compose.yaml"),
        "CLUE_COMPOSE_ENV": str(tmp_path / "compose.env"),
    }


def _run(script: str, env: dict[str, str], **extra: str) -> tuple[int, str, list[str]]:
    result = subprocess.run(
        ["bash", str(VM / script)],
        env={**env, **extra},
        capture_output=True,
        text=True,
        check=False,
    )
    log = Path(env["CALLS_LOG"])
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return result.returncode, result.stdout + result.stderr, calls


def _uploads(calls: list[str]) -> list[str]:
    return [c for c in calls if " s3 cp " in f" {c} "]


# --- backup_db.sh -------------------------------------------------------------------------------


def test_a_good_dump_is_uploaded_and_checked_in(sandbox: dict[str, str]) -> None:
    code, out, calls = _run("backup_db.sh", sandbox)
    assert code == 0, out
    assert len(_uploads(calls)) == 1
    assert "s3://clue-backups/db-backups/clue-" in _uploads(calls)[0]
    assert any(c.startswith("curl ") and "sentry.example/backup" in c for c in calls)


def test_an_empty_dump_fails_and_uploads_nothing(sandbox: dict[str, str]) -> None:
    code, out, calls = _run("backup_db.sh", sandbox, FAKE_DUMP_EMPTY="1")
    assert code != 0
    assert "empty dump" in out
    assert _uploads(calls) == []
    assert not any(c.startswith("curl ") for c in calls), "a failed backup must not check in"


def test_an_unreadable_dump_fails_and_uploads_nothing(sandbox: dict[str, str]) -> None:
    code, _out, calls = _run("backup_db.sh", sandbox, FAKE_RESTORE_FAIL="1")
    assert code != 0
    assert _uploads(calls) == []
    assert not any(c.startswith("curl ") for c in calls)


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        # The app's fleet workers sweep every key in their bucket that has no `artifact` row
        # (clue_storage.sweep_orphan_blobs), so a dump there is deleted within a day.
        ("R2_BUCKET=clue-backups", "R2_BUCKET=clue-prod"),
        # One key for both would let a leaked app key, or an app bug, delete the backups.
        ("AWS_ACCESS_KEY_ID=backup-key", "AWS_ACCESS_KEY_ID=app-key"),
    ],
)
def test_backups_refuse_the_apps_bucket_or_key(
    sandbox: dict[str, str], line: str, reason: str
) -> None:
    env_file = Path(sandbox["CLUE_BACKUP_ENV"])
    env_file.write_text(env_file.read_text(encoding="utf-8").replace(line, reason), "utf-8")
    code, out, calls = _run("backup_db.sh", sandbox)
    assert code != 0
    assert "must not share" in out, out
    assert not any("pg_dump" in c for c in calls), "refuse before doing any work"
    assert _uploads(calls) == []
    assert not any(c.startswith("curl ") for c in calls), "a refused backup must not check in"


def test_backups_refuse_when_the_app_env_cannot_be_read(sandbox: dict[str, str]) -> None:
    """Without the app's settings the separation cannot be proven: fail closed (and alert)."""
    code, out, calls = _run("backup_db.sh", {**sandbox, "CLUE_ENV_FILE": "/nonexistent/env"})
    assert code != 0
    assert _uploads(calls) == [] and not any(c.startswith("curl ") for c in calls)


def test_retention_deletes_only_dumps_older_than_14_days(sandbox: dict[str, str]) -> None:
    today = dt.datetime.now(dt.UTC)
    old = (today - dt.timedelta(days=20)).strftime("clue-%Y%m%dT070000Z.dump")
    edge = (today - dt.timedelta(days=13)).strftime("clue-%Y%m%dT070000Z.dump")
    new = (today - dt.timedelta(days=1)).strftime("clue-%Y%m%dT070000Z.dump")
    code, out, calls = _run(
        "backup_db.sh", sandbox, FAKE_BACKUPS=f"{old},{edge},{new},unrelated.txt"
    )
    assert code == 0, out
    removed = [c for c in calls if " s3 rm " in f" {c} "]
    assert len(removed) == 1 and old in removed[0], removed


# --- watchdog.sh --------------------------------------------------------------------------------


def test_a_healthy_vm_checks_in(sandbox: dict[str, str]) -> None:
    code, out, calls = _run("watchdog.sh", sandbox, FAKE_RUNNING=ALL_SERVICES)
    assert code == 0, out
    assert any(c.startswith("curl ") and "sentry.example/watchdog" in c for c in calls)


@pytest.mark.parametrize(
    ("extra", "reason"),
    [
        ({"FAKE_MEM_USED": "90"}, "memory at 90%"),
        ({"FAKE_DISK_USED": "85"}, "disk at 85%"),
        ({"FAKE_RUNNING": ALL_SERVICES.replace("design,", "")}, "design not running"),
    ],
)
def test_an_unhealthy_vm_does_not_check_in(
    sandbox: dict[str, str], extra: dict[str, str], reason: str
) -> None:
    env = {"FAKE_RUNNING": ALL_SERVICES, **extra}
    code, out, calls = _run("watchdog.sh", sandbox, **env)
    assert code != 0
    assert reason in out
    assert not any(c.startswith("curl ") for c in calls), "a missed check-in is the alert"
