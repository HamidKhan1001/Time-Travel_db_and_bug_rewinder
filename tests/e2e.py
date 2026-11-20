import os, sys
os.environ["TT_PACE"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from timetravel import seed, db, agent, appcode

seed.reset()
c = db.connect()
before_units = c.execute("select sum(stock) from inventory").fetchone()[0]
import time; time.sleep(1)
r = appcode.fn("sync_stock")(c, {"sku": "APX-0007", "stock": 0})
assert r["updated_rows"] == 1420, r
assert c.execute("select sum(stock) from inventory").fetchone()[0] == 0
seed.demo_orders()
s = agent.start("Take the business back to 2 minutes ago, keep the 3 orders that came in after the crash, and fix the bug that caused it.", background=False)
assert s.phase == "awaiting_approval", (s.phase, s.events[-1])
for e in s.events: print(f"[{e['agent']}] {e['msg']}")
print(s.plan["risk"], [c["name"] for c in s.plan["dry_run"] if not c["ok"]])
print(s.patch["diff"])
assert s.plan["orders_preserved"] >= 3 and len(s.plan["conflicts"]) == 1
agent.approve(s.id)
c = db.connect()
print("units after", c.execute("select sum(stock) from inventory").fetchone()[0], "was", before_units)
print(dict(c.execute("select sku, stock from inventory where sku in ('APX-0042','APX-0777','APX-0100')").fetchall()[0]))
print(c.execute("select id,status from orders where id>1040").fetchall() and [tuple(x) for x in c.execute("select id,status from orders where id>1040")])
r = appcode.fn("sync_stock")(c, {"sku": "APX-0007", "stock": 0})
assert r["updated_rows"] == 1, r
assert c.execute("select count(*) from inventory where stock=0").fetchone()[0] <= 2
print("bug no longer wipes; zero rows:", c.execute("select count(*) from inventory where stock=0").fetchone()[0])
agent.undo(s.id)
c = db.connect()
assert appcode.fn("sync_stock")(c, {"sku": "APX-0007", "stock": 5})["updated_rows"] == 1420
print("undo OK (buggy code back)")
seed.reset(); print("E2E PASS")
