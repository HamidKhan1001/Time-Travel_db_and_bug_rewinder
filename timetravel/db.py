"""SQLite layer: schema, change-data-capture triggers (the 'WAL stream'), clone + rewind."""
import json
import os
import sqlite3
import threading
import time

from . import config

BASE = config.BASE_DIR
DATA = config.load().data_dir          # TT_DATA_DIR overrides the default ./data
LIVE = os.path.join(DATA, "live.db")
LOCK = threading.RLock()

# table -> primary key column (all single-column so the changelog can address rows)
TABLES = {"customers": "id", "inventory": "sku", "orders": "id", "order_items": "id"}


class _Clock:
    """Controllable clock so the seed script can backdate history deterministically."""
    offset = 0.0

    def now(self):
        return time.time() + self.offset


clock = _Clock()

SCHEMA = """
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL);
CREATE TABLE inventory (
  sku TEXT PRIMARY KEY, name TEXT NOT NULL,
  stock INTEGER NOT NULL CHECK (stock >= 0), price_cents INTEGER NOT NULL);
CREATE TABLE orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  total_cents INTEGER NOT NULL, status TEXT NOT NULL,
  idem_key TEXT UNIQUE, created_at REAL NOT NULL);
CREATE TABLE order_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES orders(id),
  sku TEXT NOT NULL REFERENCES inventory(sku),
  qty INTEGER NOT NULL, unit_cents INTEGER NOT NULL);
CREATE TABLE query_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  source TEXT, sql TEXT, rows_affected INTEGER);
CREATE TABLE changelog (            -- row-level change stream (our WAL/CDC feed)
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  tbl TEXT NOT NULL, op TEXT NOT NULL, pk, old TEXT, new TEXT);
"""


DROP_ALL = """
DROP TABLE IF EXISTS session_audit_events;
DROP TABLE IF EXISTS changelog;
DROP TABLE IF EXISTS query_log;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS inventory;
DROP TABLE IF EXISTS customers;
"""


def connect(path=LIVE):
    from .recovery import transaction_logger
    from . import audit
    c = sqlite3.connect(path, timeout=30, check_same_thread=False, isolation_level=None,
                        factory=transaction_logger.RecoveryConnection)
    c.row_factory = sqlite3.Row
    c.create_function("app_now", 0, clock.now)
    c.execute("PRAGMA foreign_keys=ON")
    if path != ":memory:":
        # WAL lets readers (state polling, SSE) run while a writer commits instead of blocking on it.
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
    transaction_logger.install(c, clock.now)
    audit.ensure_schema(c)
    return c


def create_schema(c):
    c.executescript(DROP_ALL)
    c.executescript(SCHEMA)
    c.execute("INSERT INTO sqlite_sequence(name, seq) VALUES ('orders', 1000)")
    for t, pk in TABLES.items():
        cols = [r["name"] for r in c.execute(f"PRAGMA table_info({t})")]
        o = ",".join(f"'{x}',OLD.{x}" for x in cols)
        n = ",".join(f"'{x}',NEW.{x}" for x in cols)
        c.execute(f"CREATE TRIGGER {t}_ai AFTER INSERT ON {t} BEGIN INSERT INTO changelog(ts,tbl,op,pk,old,new) "
                  f"VALUES(app_now(),'{t}','I',NEW.{pk},NULL,json_object({n})); END")
        c.execute(f"CREATE TRIGGER {t}_au AFTER UPDATE ON {t} BEGIN INSERT INTO changelog(ts,tbl,op,pk,old,new) "
                  f"VALUES(app_now(),'{t}','U',NEW.{pk},json_object({o}),json_object({n})); END")
        c.execute(f"CREATE TRIGGER {t}_ad AFTER DELETE ON {t} BEGIN INSERT INTO changelog(ts,tbl,op,pk,old,new) "
                  f"VALUES(app_now(),'{t}','D',OLD.{pk},json_object({o}),NULL); END")
    from .recovery import transaction_logger
    transaction_logger.ensure_schema(c, TABLES, clock.now)
    from . import audit
    audit.ensure_schema(c)
    ensure_indexes(c)


def ensure_indexes(c):
    """Idempotent indexes for databases created before they existed. Safe to call on every start."""
    has_changelog = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='changelog'").fetchone()
    if has_changelog:
        c.execute("CREATE INDEX IF NOT EXISTS ix_changelog_ts ON changelog(ts)")


def last_change_id(conn):
    """Highest changelog id ever issued: O(1) (rowid lookup), unlike COUNT(*) which scans the table."""
    return conn.execute("SELECT COALESCE(MAX(id), 0) FROM changelog").fetchone()[0]


def prune_changelog(conn, keep_rows, batch=5000):
    """Bound the legacy changelog to the newest `keep_rows` rows. Returns how many rows were deleted.

    Rewinding further back than the oldest kept row is no longer possible, so keep_rows <= 0 disables pruning.
    Deletes in small batches so a writer is never blocked for long.
    """
    if keep_rows <= 0:
        return 0
    cutoff = last_change_id(conn) - keep_rows
    deleted = 0
    while cutoff > 0:
        n = conn.execute("DELETE FROM changelog WHERE id IN (SELECT id FROM changelog WHERE id <= ? LIMIT ?)",
                         (cutoff, batch)).rowcount
        deleted += n
        if n < batch:
            break
    return deleted


def clone(src_conn, dest_path):
    """Consistent point-in-time clone of a database (the 'ephemeral branch')."""
    if dest_path != ":memory:" and os.path.exists(dest_path):
        os.remove(dest_path)
    dest = connect(dest_path)
    src_conn.backup(dest)
    return dest


def reverse_changes(conn, since_ts, events):
    """Undo every logged change with ts > since_ts, newest first. `events` read from live log."""
    for e in events:
        tbl, pk_col = e["tbl"], TABLES[e["tbl"]]
        old = json.loads(e["old"]) if e["old"] else None
        if e["op"] == "I":
            conn.execute(f"DELETE FROM {tbl} WHERE {pk_col}=?", (e["pk"],))
        elif e["op"] == "U":
            sets = [k for k in old if k != pk_col]
            conn.execute(f"UPDATE {tbl} SET " + ",".join(f"{k}=?" for k in sets) + f" WHERE {pk_col}=?",
                         [old[k] for k in sets] + [e["pk"]])
        else:  # D
            ks = list(old)
            conn.execute(f"INSERT INTO {tbl}({','.join(ks)}) VALUES({','.join('?' * len(ks))})",
                         [old[k] for k in ks])


def changes_after(conn, ts):
    # The subquery lets SQLite range-scan ix_changelog_ts; a plain "WHERE ts > ? ORDER BY id DESC" scans the table.
    return conn.execute("SELECT * FROM changelog WHERE id IN (SELECT id FROM changelog WHERE ts > ?) "
                        "ORDER BY id DESC", (ts,)).fetchall()
