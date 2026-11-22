"""Durable SQLite transaction history backed by triggers and connection-local state."""
import json
import sqlite3
import threading
import time

STATE_TABLE = "recovery_transactions"
HISTORY_TABLE = "transaction_history"
SUPPORTED_OPERATIONS = ("I", "U", "D")
_WRITE_KEYWORDS = ("INSERT", "UPDATE", "DELETE", "REPLACE")

_lock = threading.RLock()
_states = {}


class _ConnectionState:
    __slots__ = ("token", "bound_token", "transaction_id", "event_seq", "clock", "internal_write")

    def __init__(self, clock):
        self.token = 0
        self.bound_token = None
        self.transaction_id = None
        self.event_seq = 0
        self.clock = clock or time.time
        self.internal_write = False


def _state(conn):
    with _lock:
        state = _states.get(conn)
        if state is None:
            state = _ConnectionState(time.time)
            _states[conn] = state
        return state


class RecoveryConnection(sqlite3.Connection):
    """SQLite connection that marks transaction boundaries before Python-level writes."""

    def _before_statement(self, sql):
        if not isinstance(sql, str):
            return
        statement = sql.strip()
        if not statement:
            return
        keyword = statement.split(None, 1)[0].upper()
        with _lock:
            state = _state(self)
            if state.internal_write:
                return
        if keyword == "BEGIN" or (keyword in _WRITE_KEYWORDS and not self.in_transaction):
            _new_token(self)

    def execute(self, *args, **kwargs):
        if args:
            self._before_statement(args[0])
        elif "sql" in kwargs:
            self._before_statement(kwargs["sql"])
        return super().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        if args:
            self._before_statement(args[0])
        elif "sql" in kwargs:
            self._before_statement(kwargs["sql"])
        return super().executemany(*args, **kwargs)


def _new_token(conn):
    with _lock:
        state = _state(conn)
        state.token += 1
        state.bound_token = None
        state.transaction_id = None
        state.event_seq = 0


def _json_value(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _ensure_transaction(conn):
    state = _state(conn)
    with _lock:
        if state.bound_token == state.token and state.transaction_id is not None:
            return state.transaction_id
        state.internal_write = True
        try:
            cur = conn.execute(
                f"INSERT INTO {STATE_TABLE}(started_at, source) VALUES(?, ?)",
                (state.clock(), "sqlite-trigger"))
        finally:
            state.internal_write = False
        state.transaction_id = int(cur.lastrowid)
        state.bound_token = state.token
        state.event_seq = 0
        return state.transaction_id


def _next_event_seq(conn):
    _ensure_transaction(conn)
    state = _state(conn)
    with _lock:
        state.event_seq += 1
        return state.event_seq


def install(conn, clock=None):
    """Register the SQL functions required by the durable history triggers."""
    with _lock:
        state = _states.get(conn)
        if state is None:
            state = _ConnectionState(clock)
            _states[conn] = state
        elif clock is not None:
            state.clock = clock
    conn.create_function("recovery_txn_id", 0, lambda: _ensure_transaction(conn))
    conn.create_function("recovery_event_seq", 0, lambda: _next_event_seq(conn))
    conn.create_function("recovery_json", 1, _json_value)
    return conn


def uninstall(conn):
    """Detach connection-local history state."""
    with _lock:
        _states.pop(conn, None)
    return conn


def _table_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _table_columns(conn, table):
    if not _table_exists(conn, table):
        raise RuntimeError(f"transaction logger requires missing table: {table}")
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]


def _allowed_tables_sql(tables):
    return ",".join("'" + name.replace("'", "''") + "'" for name in sorted(tables))


def _history_schema(tables):
    allowed = _allowed_tables_sql(tables)
    return f"""
    CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      started_at REAL NOT NULL,
      source TEXT
    );
    CREATE TABLE IF NOT EXISTS {HISTORY_TABLE} (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      transaction_id INTEGER NOT NULL REFERENCES {STATE_TABLE}(id),
      event_seq INTEGER NOT NULL,
      ts REAL NOT NULL,
      tbl TEXT NOT NULL CHECK (tbl IN ({allowed})),
      pk,
      pk_json TEXT NOT NULL,
      op TEXT NOT NULL CHECK (op IN ('I', 'U', 'D')),
      old_values TEXT,
      new_values TEXT,
      UNIQUE(transaction_id, event_seq)
    );
    CREATE INDEX IF NOT EXISTS ix_transaction_history_event ON {HISTORY_TABLE}(id);
    CREATE INDEX IF NOT EXISTS ix_transaction_history_group ON {HISTORY_TABLE}(transaction_id, event_seq);
    CREATE INDEX IF NOT EXISTS ix_transaction_history_table ON {HISTORY_TABLE}(tbl, pk);
    CREATE TABLE IF NOT EXISTS recovery_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      started_at REAL NOT NULL,
      finished_at REAL,
      plan_fingerprint TEXT NOT NULL,
      anchor_event_id INTEGER NOT NULL,
      selection TEXT NOT NULL,
      step_count INTEGER NOT NULL,
      status TEXT NOT NULL CHECK (status IN ('started', 'committed', 'rolled-back')),
      detail TEXT
    );
    CREATE TABLE IF NOT EXISTS recovery_actions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      run_id INTEGER NOT NULL REFERENCES recovery_runs(id),
      source_event_id INTEGER NOT NULL,
      transaction_id INTEGER NOT NULL,
      op TEXT NOT NULL CHECK (op IN ('I', 'U', 'D')),
      tbl TEXT NOT NULL,
      pk_json TEXT NOT NULL,
      status TEXT NOT NULL CHECK (status IN ('applied', 'failed')),
      ts REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_recovery_actions_run ON recovery_actions(run_id, id);
    """


def _trigger_sql(table, pk, columns, op, old_json, new_json):
    row_alias = "OLD" if op == "DELETE" else "NEW"
    return f"""
    CREATE TRIGGER IF NOT EXISTS recovery_{table}_{op.lower()} AFTER {op} ON {table}
    BEGIN
      INSERT INTO {HISTORY_TABLE}(transaction_id, event_seq, ts, tbl, pk, pk_json, op, old_values, new_values)
      VALUES (recovery_txn_id(), recovery_event_seq(), app_now(), '{table}',
              {row_alias}.{pk},
              recovery_json({row_alias}.{pk}),
              '{op[0]}', {old_json}, {new_json});
    END
    """


def ensure_schema(conn, tables, clock=None):
    """Create the durable history tables and triggers additively."""
    if conn.in_transaction:
        raise RuntimeError("history schema cannot be installed inside an open transaction")
    install(conn, clock)
    triggers = []
    for table, pk in tables.items():
        columns = _table_columns(conn, table)
        if pk not in columns:
            raise RuntimeError(f"primary key {pk} is missing from table {table}")
        old_pairs = ",".join(f"'{col}', OLD.{col}" for col in columns)
        new_pairs = ",".join(f"'{col}', NEW.{col}" for col in columns)
        triggers.append(_trigger_sql(table, pk, columns, "INSERT", "NULL", f"json_object({new_pairs})"))
        triggers.append(_trigger_sql(table, pk, columns, "UPDATE", f"json_object({old_pairs})", f"json_object({new_pairs})"))
        triggers.append(_trigger_sql(table, pk, columns, "DELETE", f"json_object({old_pairs})", "NULL"))
    conn.executescript(_history_schema(tables))
    for statement in triggers:
        conn.execute(statement)
    return {"transactions": STATE_TABLE, "history": HISTORY_TABLE, "triggers": len(triggers)}


def history_installed(conn):
    return _table_exists(conn, STATE_TABLE) and _table_exists(conn, HISTORY_TABLE)


def schema_ready(conn, tables):
    return all(_table_exists(conn, table) for table in tables)


def capture_scope(tables):
    """Describe exactly what the installed logger captures."""
    return {
        "tables": sorted(tables),
        "operations": list(SUPPORTED_OPERATIONS),
        "excluded": ["DDL", "query_log", "changelog", "sqlite_sequence", "savepoints",
                     "recovery_runs", "recovery_actions"],
    }


def sqlite_connection_type():
    return RecoveryConnection
