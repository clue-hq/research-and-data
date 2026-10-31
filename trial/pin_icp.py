"""Point the trial project at one of its earlier ICP pins (appends a pin row, as production does).

    uv run python trial/pin_icp.py brokers    # freight-brokers-net-new  (NTG, Nav)
    uv run python trial/pin_icp.py shippers   # enterprise-shippers-net-new (C&S, Worldpac)
"""
import os, sys
import psycopg

URL = os.environ["CLUE_DATABASE_URL"]
if not URL.endswith("/clue_addis-ababa"):
    sys.exit("refused: not the addis-ababa lane database")
PROJECT = "prj_bcbca9a562a15149875c552222ee7c8f"
DOCS = {"brokers": "8c005e93-374e-508c-8cc4-1a1326678ec5", "shippers": "249355e7-a3d3-50be-9c8c-0b27ee0ed96f"}

with psycopg.connect(URL.replace("postgresql+asyncpg://", "postgresql://")) as conn:
    cur = conn.cursor()
    cur.execute("""insert into project_icp_pin (workspace_id, project_id, pin_seq, brand_id, document_id,
                     icp_key, artifact_key, artifact_sha256, product_selection_version, pinned_by_user_id)
                   select workspace_id, project_id,
                          (select max(pin_seq)+1 from project_icp_pin where project_id=%s),
                          brand_id, document_id, icp_key, artifact_key, artifact_sha256,
                          product_selection_version, pinned_by_user_id
                   from project_icp_pin where project_id=%s and document_id=%s
                   order by pin_seq limit 1""", (PROJECT, PROJECT, DOCS[sys.argv[1]]))
    cur.execute("select pin_seq, icp_key from project_icp_pin where project_id=%s order by pin_seq desc limit 1", (PROJECT,))
    print("current pin:", cur.fetchone())
