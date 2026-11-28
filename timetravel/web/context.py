"""AppContext: the one object that carries configuration and shared state through the HTTP layer.

Everything that used to be a module global in server.py (settings, limiters, stream slots, warm-up numbers,
start time) lives here, so two servers with different settings can run in one process and tests build a context
instead of patching module attributes.
"""
import dataclasses
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .. import config
from .security import Security


@dataclass
class AppContext:
    cfg: config.Settings
    security: Security
    sse_slots: threading.BoundedSemaphore
    started_at: float = field(default_factory=time.time)
    warm: Dict[str, Any] = field(default_factory=lambda: {"ms": None, "at": None})   # last clone-speed measurement

    @classmethod
    def create(cls, cfg: Optional[config.Settings] = None, security: Optional[Security] = None) -> "AppContext":
        cfg = cfg or config.load()
        return cls(cfg=cfg, security=security or Security(cfg),
                   sse_slots=threading.BoundedSemaphore(cfg.max_sse_streams))

    def reconfigure(self, **changes) -> config.Settings:
        """Swap settings on a running context (tests and operators' REPLs). Limiters keep their current buckets."""
        self.cfg = dataclasses.replace(self.cfg, **changes)
        self.security.cfg = self.cfg
        return self.cfg
