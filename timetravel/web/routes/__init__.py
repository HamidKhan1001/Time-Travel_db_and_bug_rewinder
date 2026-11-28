"""One module per area of the API. ``build_router`` is the single place that lists them all."""
from ..router import Router
from . import audit, demo, health, orders, recovery, state, ui


def build_router() -> Router:
    router = Router()
    for module in (health, ui, state, audit, recovery, orders, demo):   # order matters only inside a module
        module.register(router)
    return router
