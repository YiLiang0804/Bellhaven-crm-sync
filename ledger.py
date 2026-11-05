"""Decision ledger. Makes re-runs idempotent: a proposal key that was already approved/rejected is never re-proposed."""
import sqlite3
import json
from datetime import datetime, timezone
import config


def _conn():
    c = sqlite3.connect(config.LEDGER_DB)
    c.execute("""CREATE TABLE IF NOT EXISTS decisions (
        key TEXT PRIMARY KEY, decision TEXT, decided_at TEXT, proposal TEXT, result TEXT)""")
    return c


def decided_keys() -> set:
    with _conn() as c:
        return {row[0] for row in c.execute("SELECT key FROM decisions")}


def record(key: str, decision: str, proposal: dict, result=None):
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO decisions VALUES (?,?,?,?,?)",
                  (key, decision, datetime.now(timezone.utc).isoformat(), json.dumps(proposal), json.dumps(result)))


def history():
    with _conn() as c:
        return [dict(key=k, decision=d, decided_at=t, proposal=json.loads(p), result=json.loads(r) if r else None)
                for k, d, t, p, r in c.execute("SELECT * FROM decisions ORDER BY decided_at DESC")]
