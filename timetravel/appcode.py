"""Loads the live application code from source text (so patch / undo take effect instantly)."""
import os
from .db import BASE

HANDLERS_PATH = os.path.join(BASE, "app", "handlers.py")
PRISTINE_PATH = os.path.join(BASE, "seed", "handlers_buggy.py.txt")
_ns = {}


def read_source(path=HANDLERS_PATH):
    with open(path) as f:
        return f.read()


def write_source(text):
    with open(HANDLERS_PATH, "w") as f:
        f.write(text)
    reload()


def reload():
    ns = {"__name__": "handlers"}
    exec(compile(read_source(), HANDLERS_PATH, "exec"), ns)
    _ns.clear()
    _ns.update(ns)


def fn(name):
    if not _ns:
        reload()
    return _ns[name]
