import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from timetravel import db

DEFAULT_SEED = 20261122
FIXED_EPOCH = 1_760_000_000.0


def batched(values, size):
    batch = []
    for value in values:
        batch.append(value)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def generate_dataset(rows, path, seed=DEFAULT_SEED, customers=10, orders=20,
                     items=20, batch_size=5000):
    if rows < 1:
        raise ValueError("rows must be positive")
    if customers < 1 or orders < 0 or items < 0:
        raise ValueError("customers must be positive and orders/items non-negative")
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)

    original_offset = db.clock.offset
    db.clock.offset = FIXED_EPOCH - time.time()
    conn = db.connect(path)
    try:
        db.create_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            "INSERT INTO customers(id, name, email) VALUES(?, ?, ?)",
            [(index, f"Customer {index}", f"customer{index}@bench.example")
             for index in range(1, customers + 1)])

        for batch in batched(range(rows), batch_size):
            conn.executemany(
                "INSERT INTO inventory(sku, name, stock, price_cents) VALUES(?, ?, ?, ?)",
                [(f"SKU-{index:08d}", f"Item {index}",
                  (index * 37) % 1000 + 1, (index * 97) % 10000 + 100)
                 for index in batch])

        for batch in batched(range(1, orders + 1), batch_size):
            conn.executemany(
                "INSERT INTO orders(id, customer_id, total_cents, status, idem_key, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                [(1000 + index, (index % customers) + 1,
                  (index * 311) % 50000 + 100, "paid",
                  f"bench-{seed}-{index}", FIXED_EPOCH + index)
                 for index in batch])

        for batch in batched(range(1, items + 1), batch_size):
            conn.executemany(
                "INSERT INTO order_items(id, order_id, sku, qty, unit_cents) VALUES(?, ?, ?, ?, ?)",
                [(index, 1000 + ((index - 1) % orders) + 1,
                  f"SKU-{((index - 1) % rows):08d}", (index % 3) + 1,
                  (index * 53) % 5000 + 50)
                 for index in batch])
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
        db.clock.offset = original_offset

    return {
        "db_path": path,
        "rows": rows,
        "seed": seed,
        "customers": customers,
        "orders": orders,
        "order_items": items,
        "batch_size": batch_size,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate deterministic recovery benchmark data.")
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--customers", type=int, default=10)
    parser.add_argument("--orders", type=int, default=20)
    parser.add_argument("--items", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()
    summary = generate_dataset(args.rows, args.db, args.seed, args.customers,
                               args.orders, args.items, args.batch_size)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
