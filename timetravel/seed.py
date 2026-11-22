"""Deterministic demo seed + reset. Run `python3 reset.py` between takes."""
import glob
import os
import random

from . import appcode, db

ADJ = ["Alpine", "Summit", "Ridge", "Trail", "Granite", "Cascade", "Boreal", "Apex", "Glacier", "Canyon"]
THING = ["Jacket", "Daypack", "Boots", "Poles", "Tent", "Bottle", "Gloves", "Headlamp", "Beanie", "Stove"]
SPECIAL = {
    "APX-0007": ("Alpine Water Bottle", 120, 2400),
    "APX-0042": ("Summit Pro Jacket", 35, 18900),
    "APX-0100": ("Trailhead Daypack", 60, 7400),
    "APX-0555": ("Ridge Trekking Poles", 44, 5900),
    "APX-0777": ("Limited Edition Trail Pack", 2, 24900),
}
N_SKUS = 1420
NAMES = ["Ava Chen", "Ben Ortiz", "Cleo Park", "Dev Patel", "Eli Novak", "Fay Moreau",
         "Gus Lindqvist", "Hana Sato", "Ivo Petrov", "Jo Mensah", "Kai Rossi", "Lia Haddad"]


def reset():
    import gc
    appcode.write_source(appcode.read_source(appcode.PRISTINE_PATH))   # restore the buggy code
    gc.collect()
    for f in glob.glob(os.path.join(db.DATA, "*.db")):
        try:
            os.remove(f)
        except OSError:
            pass
    os.makedirs(db.DATA, exist_ok=True)
    with db.LOCK:
        c = db.connect()
        db.create_schema(c)
        rng = random.Random(42)
        db.clock.offset = -600          # inventory loaded 10 minutes ago
        c.execute("BEGIN")
        for i, n in enumerate(NAMES, 1):
            c.execute("INSERT INTO customers VALUES(?,?,?)", (i, n, n.split()[0].lower() + "@example.com"))
        for i in range(1, N_SKUS + 1):
            sku = f"APX-{i:04d}"
            name, stock, price = SPECIAL.get(sku, (f"{ADJ[i % 10]} {THING[(i // 10) % 10]} {i}",
                                                   rng.randint(8, 220), rng.randint(1500, 30000)))
            c.execute("INSERT INTO inventory VALUES(?,?,?,?)", (sku, name, stock, price))
        c.execute("COMMIT")
        place = appcode.fn("place_order")
        for k in range(40):             # healthy history: orders 1001-1040 between -9 and -3 minutes
            db.clock.offset = -(540 - k * 9)
            sku = f"APX-{rng.randint(1, N_SKUS):04d}"
            if sku in SPECIAL:
                sku = "APX-0001"
            place(c, {"customer_id": rng.randint(1, 12), "idem_key": f"seed-{k}",
                      "items": [{"sku": sku, "qty": rng.randint(1, 2)}]})
        db.clock.offset = 0
        c.close()


def demo_orders():
    """Three customers order right after the crash. #1043 buys 3 of a SKU with only 2 left."""
    place = appcode.fn("place_order")
    batches = [
        (1, [{"sku": "APX-0042", "qty": 1}, {"sku": "APX-0100", "qty": 2}]),
        (2, [{"sku": "APX-0555", "qty": 1}]),
        (3, [{"sku": "APX-0777", "qty": 3}]),
    ]
    out = []
    with db.LOCK:
        c = db.connect()
        for cid, items in batches:
            out.append(place(c, {"customer_id": cid, "items": items}))
        c.close()
    return out
