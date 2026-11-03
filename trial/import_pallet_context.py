"""Load the exported Pallet context into the trial lane database, verbatim (same ids).

    set -a; source ../.env; set +a
    uv run python trial/import_pallet_context.py <export.json>

Refuses unless CLUE_DATABASE_URL names the research-trial database (clue_research_trial). Writes the document blobs
into the lane's filesystem storage under their original keys. Re-running is a no-op
(ON CONFLICT DO NOTHING).
"""
import base64, json, os, sys
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

URL = os.environ["CLUE_DATABASE_URL"]
if not URL.endswith("/clue_research_trial"):
    sys.exit(f"refused: CLUE_DATABASE_URL is not the research-trial database (clue_research_trial)")
STORAGE_ROOT = Path(os.environ["CLUE_STORAGE_FS_ROOT"])

ORDER = ["platform_user", "workspace", "brand", "product", "project", "project_product",
         "artifact", "brand_knowledge_document", "project_icp_pin", "account_entity",
         "project_account"]
# Foreign keys to rows this trial does not copy (onboarding steps, agent turns, product changes).
NULLED = {"brand_knowledge_document": {"produced_by_step_id", "produced_by_turn_id"},
          "project_product": {"product_change_id"}}
# Self references: a document is inserted only after every document it names.
SELF_REFS = ("derived_from_document_id", "source_icp_document_id", "supersedes_document_id")


def dependency_order(docs: list[dict]) -> list[dict]:
    done: set[str] = set(); ordered: list[dict] = []; pending = list(docs)
    while pending:
        ready = [d for d in pending if all(not d.get(c) or d[c] in done for c in SELF_REFS)]
        if not ready:
            raise SystemExit("document references form a cycle or name a document not exported")
        for d in ready:
            ordered.append(d); done.add(d["document_id"]); pending.remove(d)
    return ordered


def dec(v):
    if isinstance(v, dict) and set(v) == {"__dt__"}: return datetime.fromisoformat(v["__dt__"])
    if isinstance(v, dict) and set(v) == {"__dec__"}: return v["__dec__"]
    if isinstance(v, dict) and set(v) == {"__b64__"}: return base64.b64decode(v["__b64__"])
    return v


def main(path: str) -> None:
    data = json.loads(Path(path).read_text())
    with psycopg.connect(URL.replace("postgresql+asyncpg://", "postgresql://")) as conn:
        cur = conn.cursor()
        for table in ORDER:
            cur.execute("select column_name, data_type from information_schema.columns "
                        "where table_name=%s and table_schema='public'", (table,))
            types = dict(cur.fetchall())
            inserted = 0
            source = dependency_order(data[table]) if table == "brand_knowledge_document" else data[table]
            for row in source:
                if row.get("status") == "merged" and table in ("product", "account_entity"):
                    continue  # merged rows are not in the project's selection; skipped
                values = {}
                for col, raw in row.items():
                    if col not in types: continue
                    v = dec(raw)
                    if col in NULLED.get(table, ()): v = None
                    if types[col] in ("json", "jsonb") and v is not None: v = Jsonb(v)
                    values[col] = v
                cols = ", ".join(f'"{c}"' for c in values)
                marks = ", ".join(["%s"] * len(values))
                cur.execute(f'insert into "{table}" ({cols}) values ({marks}) on conflict do nothing',
                            list(values.values()))
                inserted += cur.rowcount
            print(f"{table}: {inserted} of {len(data[table])} inserted")
        conn.commit()
    written = 0
    for key, b64 in data["__blobs__"].items():
        target = STORAGE_ROOT / key
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base64.b64decode(b64))
            written += 1
    print(f"blobs written: {written} of {len(data['__blobs__'])}")


if __name__ == "__main__":
    main(sys.argv[1])
