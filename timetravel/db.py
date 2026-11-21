"""SQLite layer: schema, change-data-capture triggers (the 'WAL stream'), clone + rewind."""
import json
import os
import sqlite3
import threading
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
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
DROP TABLE IF EXISTS changelog;
DROP TABLE IF EXISTS query_log;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS inventory;
DROP TABLE IF EXISTS customers;
"""


def connect(path=LIVE):
    c = sqlite3.connect(path, timeout=30, check_same_thread=False, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.create_function("app_now", 0, clock.now)
    c.execute("PRAGMA foreign_keys=ON")
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
    return conn.execute("SELECT * FROM changelog WHERE ts > ? ORDER BY id DESC", (ts,)).fetchall()
