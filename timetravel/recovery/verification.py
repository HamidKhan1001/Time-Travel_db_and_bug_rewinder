"""Checksum-based verification of recovered database state."""
import base64
import hashlib
import json
import math
import os
import shutil
import sqlite3
import tempfile
from typing import Any, Sequence

from .. import db

BATCH_SIZE = 1000
CHECKSUM_TABLE = "row_checksums"


class VerificationBaseline:
    def __init__(self, checksum_path, database_checksum, row_count, tables, label, owned_paths=()):
        self.checksum_path = checksum_path
        self.database_checksum = database_checksum
        self.row_count = row_count
        self.tables = dict(tables)
        self.label = label
        self._owned_paths = list(owned_paths)
        self._closed = False

    def close(self):
        if self._closed:
            return
        self._closed = True
        for path in self._owned_paths:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "__float__:nan"
        if math.isinf(value):
            return "__float__:inf" if value > 0 else "__float__:-inf"
        return format(value, ".15g")
    if isinstance(value, bytes):
        return {"__blob__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (int, str)):
        return value
    return str(value)


def canonical_json(value: Any) -> str:
    return json.dumps(normalize_value(value), ensure_ascii=False, separators=(",", ":"))


def _canonical_row_ordered(columns: Sequence[str], row: Any) -> str:
    payload = [[column, normalize_value(row[column])] for column in columns]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def canonical_row(columns: Sequence[str], row: Any) -> str:
    return _canonical_row_ordered(sorted(columns), row)


def _row_checksum(table: str, ordered_columns: Sequence[str], row: Any) -> str:
    digest = hashlib.sha256()
    digest.update(table.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(_canonical_row_ordered(ordered_columns, row).encode("utf-8"))
    return digest.hexdigest()


def row_checksum(table: str, columns: Sequence[str], row: Any, exclude=()) -> str:
    selected = sorted(column for column in columns if column not in exclude)
    return _row_checksum(table, selected, row)


def _columns(conn, table):
    rows = conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
    return [row["name"] for row in sorted(rows, key=lambda item: item["cid"])]


def _checksum_db_path(directory):
    return os.path.join(directory, "checksums.db")


def _database_checksum(conn):
    digest = hashlib.sha256()
    rows = conn.execute(
        f"SELECT tbl, pk_json, row_checksum FROM {CHECKSUM_TABLE} ORDER BY tbl, pk_json")
    for table, pk_json, checksum in rows:
        digest.update(table.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(pk_json.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(checksum.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def build_baseline(conn, tables=None, label="baseline", directory=None):
    """Stream rows into a checksum database and return a deterministic baseline."""
    tables = tables or db.TABLES
    owned = []
    if directory is None:
        directory = tempfile.mkdtemp(prefix="tt-verify-")
        owned.append(directory)
    else:
        os.makedirs(directory, exist_ok=True)
    checksum_path = _checksum_db_path(directory)
    if os.path.exists(checksum_path):
        os.remove(checksum_path)

    checksum_conn = sqlite3.connect(checksum_path)
    try:
        checksum_conn.execute("PRAGMA journal_mode=OFF")
        checksum_conn.execute("PRAGMA synchronous=OFF")
        checksum_conn.execute(
            f"CREATE TABLE {CHECKSUM_TABLE}(tbl TEXT NOT NULL, pk_json TEXT NOT NULL, "
            "row_checksum TEXT NOT NULL, content_checksum TEXT NOT NULL, "
            "PRIMARY KEY(tbl, pk_json)) WITHOUT ROWID")
        insert_sql = (
            f"INSERT INTO {CHECKSUM_TABLE}"
            "(tbl, pk_json, row_checksum, content_checksum) VALUES(?, ?, ?, ?)")
        total = 0
        for table in sorted(tables):
            pk_column = tables[table]
            ordered_columns = sorted(_columns(conn, table))
            content_columns = [column for column in ordered_columns if column != pk_column]
            cursor = conn.execute(
                f"SELECT * FROM {_quote(table)} ORDER BY {_quote(pk_column)}")
            while True:
                batch = cursor.fetchmany(BATCH_SIZE)
                if not batch:
                    break
                params = [
                    (table, canonical_json(row[pk_column]),
                     _row_checksum(table, ordered_columns, row),
                     _row_checksum(table, content_columns, row))
                    for row in batch]
                checksum_conn.executemany(insert_sql, params)
                total += len(params)
            cursor.close()
        checksum_conn.commit()
        database_checksum = _database_checksum(checksum_conn)
        return VerificationBaseline(checksum_path, database_checksum, total, tables, label, owned)
    finally:
        checksum_conn.close()


def checksum_database(conn, tables=None):
    with build_baseline(conn, tables, label="checksum") as baseline:
        return baseline.database_checksum


def capture_reference(conn, tables=None, path=None, label="reference"):
    """Capture a consistent reference snapshot using SQLite backup isolation."""
    if conn.in_transaction:
        raise RuntimeError("reference snapshot cannot be captured inside an open transaction")
    tables = tables or db.TABLES
    if path is None:
        root = tempfile.mkdtemp(prefix="tt-reference-")
        snapshot_path = os.path.join(root, "reference.db")
        owned = [root]
    else:
        snapshot_path = path
        owned = []
    checkout = db.clone(conn, snapshot_path)
    try:
        baseline = build_baseline(checkout, tables, label=label)
        baseline._owned_paths = list(owned) + baseline._owned_paths
        return baseline
    finally:
        checkout.close()


def _attach(conn, alias, path):
    conn.execute("ATTACH DATABASE ? AS " + alias, (path,))


def _scalar(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]


def _collect_samples(original, recovered, sample_limit):
    empty = {"missing": [], "unexpected": [], "modified": [], "primary_key": []}
    if sample_limit <= 0:
        return empty
    original_conn = sqlite3.connect(original.checksum_path)
    recovered_conn = sqlite3.connect(recovered.checksum_path)
    try:
        sql = (f"SELECT tbl, pk_json, row_checksum, content_checksum "
               f"FROM {CHECKSUM_TABLE} ORDER BY tbl, pk_json")
        left = original_conn.execute(sql)
        right = recovered_conn.execute(sql)
        left_row = left.fetchone()
        right_row = right.fetchone()
        content_limit = max(sample_limit * 10, sample_limit)
        missing_content = {}
        unexpected_content = {}
        while left_row is not None or right_row is not None:
            if right_row is None or (left_row is not None
                                     and (left_row[0], left_row[1]) < (right_row[0], right_row[1])):
                if len(empty["missing"]) < sample_limit:
                    empty["missing"].append([left_row[0], left_row[1]])
                if left_row[3] not in missing_content and len(missing_content) < content_limit:
                    missing_content[left_row[3]] = (left_row[0], left_row[1])
                left_row = left.fetchone()
            elif left_row is None or (right_row[0], right_row[1]) < (left_row[0], left_row[1]):
                if len(empty["unexpected"]) < sample_limit:
                    empty["unexpected"].append([right_row[0], right_row[1]])
                if right_row[3] not in unexpected_content and len(unexpected_content) < content_limit:
                    unexpected_content[right_row[3]] = (right_row[0], right_row[1])
                right_row = right.fetchone()
            else:
                if left_row[2] != right_row[2] and len(empty["modified"]) < sample_limit:
                    empty["modified"].append([left_row[0], left_row[1]])
                left_row = left.fetchone()
                right_row = right.fetchone()
        for content, (table, old_pk) in missing_content.items():
            if content in unexpected_content and len(empty["primary_key"]) < sample_limit:
                new_table, new_pk = unexpected_content[content]
                empty["primary_key"].append([table, old_pk, new_pk])
        return empty
    finally:
        original_conn.close()
        recovered_conn.close()


def compare_baselines(original, recovered, sample_limit=5):
    """Compare two baselines by key and row checksum without loading full rows into memory."""
    conn = sqlite3.connect(":memory:")
    try:
        _attach(conn, "orig", original.checksum_path)
        _attach(conn, "rec", recovered.checksum_path)
        total, matching, mismatching, missing, unexpected = (
            int(value or 0) for value in conn.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN o.tbl IS NOT NULL AND r.tbl IS NOT NULL "
                "AND o.row_checksum = r.row_checksum THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN o.tbl IS NOT NULL AND r.tbl IS NOT NULL "
                "AND o.row_checksum <> r.row_checksum THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN o.tbl IS NOT NULL AND r.tbl IS NULL THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN o.tbl IS NULL AND r.tbl IS NOT NULL THEN 1 ELSE 0 END) "
                "FROM (SELECT tbl, pk_json FROM orig." + CHECKSUM_TABLE +
                " UNION SELECT tbl, pk_json FROM rec." + CHECKSUM_TABLE + ") AS k "
                "LEFT JOIN orig." + CHECKSUM_TABLE + " AS o ON o.tbl = k.tbl AND o.pk_json = k.pk_json "
                "LEFT JOIN rec." + CHECKSUM_TABLE + " AS r ON r.tbl = k.tbl AND r.pk_json = k.pk_json").fetchone())
        primary_key_mismatches = _scalar(conn,
            "SELECT COUNT(*) FROM ("
            "SELECT o.content_checksum FROM orig." + CHECKSUM_TABLE + " AS o LEFT JOIN rec." + CHECKSUM_TABLE + " AS r "
            "ON o.tbl = r.tbl AND o.pk_json = r.pk_json WHERE r.tbl IS NULL INTERSECT "
            "SELECT r.content_checksum FROM rec." + CHECKSUM_TABLE + " AS r LEFT JOIN orig." + CHECKSUM_TABLE + " AS o "
            "ON o.tbl = r.tbl AND o.pk_json = r.pk_json WHERE o.tbl IS NULL)")
        checksum_match = original.database_checksum == recovered.database_checksum
        verified = checksum_match and not (mismatching or missing or unexpected or primary_key_mismatches)

        samples = _collect_samples(original, recovered, sample_limit)
        return {
            "original_checksum": original.database_checksum,
            "recovered_checksum": recovered.database_checksum,
            "checksum_match": checksum_match,
            "total_rows_checked": total,
            "matching_rows": matching,
            "mismatching_rows": mismatching,
            "modified_rows": mismatching,
            "missing_rows": missing,
            "unexpected_rows": unexpected,
            "primary_key_mismatches": primary_key_mismatches,
            "integrity_status": "VERIFIED" if verified else "FAILED",
            "checked_tables": sorted(set(original.tables) | set(recovered.tables)),
            "samples": samples,
        }
    finally:
        conn.close()


def verify_state_against(conn, baseline, tables=None, sample_limit=5):
    actual = build_baseline(conn, tables or baseline.tables, label="recovered")
    try:
        return compare_baselines(baseline, actual, sample_limit=sample_limit)
    finally:
        actual.close()
