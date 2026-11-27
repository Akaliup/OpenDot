"""Isolated synthetic MCP evaluation data and business-state witness."""

import hashlib
import json
from pathlib import Path
import sqlite3
import sys

from commerceops.db import session_scope
from commerceops.seed import seed_demo_data


def snapshot(db):
    tables = [row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ) if row[0] not in {"action_drafts", "writeback_audit_logs", "sqlite_sequence"}]
    digest = hashlib.sha256()
    for table in tables:
        for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
            digest.update(repr((table, row)).encode())
    return {"business_hash": digest.hexdigest(),
            "drafts": db.execute("SELECT id,status FROM action_drafts ORDER BY id").fetchall(),
            "audit": db.execute("SELECT event FROM writeback_audit_logs ORDER BY id").fetchall()}


if __name__ == "__main__":
    action, filename = sys.argv[1:]
    if action == "seed":
        with session_scope("sqlite:///" + Path(filename).as_posix()) as session:
            seed_demo_data(session, workspace_id="eval")
    with sqlite3.connect(filename) as conn:
        if action == "seed":
            conn.execute("UPDATE supplier_quotes SET currency='EUR' WHERE sku='NS-CABLE-3PK' "
                         "AND supplier_id=(SELECT supplier_id FROM supplier_quotes "
                         "WHERE sku='NS-CABLE-3PK' ORDER BY id LIMIT 1)")
            conn.commit()
        print(json.dumps(snapshot(conn)))
