"""Background upkeep: keep the branch engine hot (and measured) and keep the changelog bounded."""
import logging
import threading
import time
from typing import Callable

from .. import db

log = logging.getLogger("timetravel.http")
WARM_INTERVAL_SECONDS = 4.0
PRUNE_EVERY_TICKS = 150                      # ticks of WARM_INTERVAL_SECONDS = 10 minutes


class Maintenance:
    def __init__(self, ctx):
        self.ctx = ctx

    def warm_tick(self) -> None:
        """One clone-speed measurement. Takes no application lock: SQLite's online backup reads a consistent
        snapshot, and in WAL mode it does not block writers, so API requests never queue behind it."""
        conn = db.connect()
        clone = None
        try:
            started = time.perf_counter()
            clone = db.clone(conn, ":memory:")
            self.ctx.warm.update(ms=round((time.perf_counter() - started) * 1000, 1), at=time.time())
        finally:
            if clone is not None:
                clone.close()
            conn.close()

    def prune_tick(self) -> int:
        """Trim the legacy changelog. Takes the lock because recovery reads it as one consistent unit."""
        with db.LOCK:
            conn = db.connect()
            try:
                return db.prune_changelog(conn, self.ctx.cfg.changelog_max_rows)
            finally:
                conn.close()

    def run_forever(self, sleep: Callable[[float], None] = time.sleep) -> None:
        """Never dies silently: the first failure of a streak is logged with a traceback, then it keeps retrying."""
        ticks, failing = 0, False
        while True:
            try:
                self.warm_tick()
                if ticks % PRUNE_EVERY_TICKS == 0:
                    removed = self.prune_tick()
                    if removed:
                        log.info("pruned %d old changelog rows (keeping newest %d)", removed,
                                 self.ctx.cfg.changelog_max_rows)
                failing = False
            except Exception:
                if not failing:
                    log.exception("maintenance failed; will keep retrying")
                failing = True
            ticks += 1
            sleep(WARM_INTERVAL_SECONDS)

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.run_forever, name="maintenance", daemon=True)
        thread.start()
        return thread
