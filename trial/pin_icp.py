"""Point a trial project at one of its earlier ICP pins (appends a pin row, as production does).

    TRIAL_PROJECT=<project id> uv run python trial/pin_icp.py brokers    # freight-brokers-net-new
    TRIAL_PROJECT=<project id> uv run python trial/pin_icp.py shippers   # enterprise-shippers-net-new
"""
import os, sys
import psycopg

URL = os.environ["CLUE_DATABASE_URL"]
if not URL.endswith("/clue_addis-ababa"):
    sys.exit("refused: not the addis-ababa lane database")
PROJECT = os.environ.get("TRIAL_PROJECT", "prj_bcbca9a562a15149875c552222ee7c8f")
KEYS = {"brokers": "freight-brokers-net-new", "shippers": "enterprise-shippers-net-new"}

with psycopg.connect(URL.replace("postgresql+asyncpg://", "postgresql://")) as conn:
    cur = conn.cursor()
    cur.execute("""insert into project_icp_pin (workspace_id, project_id, pin_seq, brand_id, document_id,
                     icp_key, artifact_key, artifact_sha256, product_selection_version, pinned_by_user_id)
                   select workspace_id, project_id,
                          (select max(pin_seq)+1 from project_icp_pin where project_id=%s),
                          brand_id, document_id, icp_key, artifact_key, artifact_sha256,
                          product_selection_version, pinned_by_user_id
                   from project_icp_pin where project_id=%s and icp_key=%s
                   order by pin_seq limit 1""", (PROJECT, PROJECT, KEYS[sys.argv[1]]))
    if cur.rowcount != 1:
        sys.exit(f"refused: no earlier pin for {KEYS[sys.argv[1]]} on {PROJECT}")
    cur.execute("select pin_seq, icp_key from project_icp_pin where project_id=%s order by pin_seq desc limit 1", (PROJECT,))
    print("current pin:", cur.fetchone())
