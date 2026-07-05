"""Shared router-module sources for the variant-aware tests."""

VARIANTS_ROUTER = """
from fastapi_router_variants import RouterWrapper

router = RouterWrapper(version=False)


@router.get("/users")
def list_users() -> None: ...


@router.get("/items", version=(1, 2))
def list_items() -> None: ...
"""

HIDDEN_ROUTER = """
from fastapi_router_variants import RouterWrapper

router = RouterWrapper(version=False, hidden=True, deployment="metrics")


@router.get("/metrics")
def metrics() -> None: ...
"""

PARENT_CHAIN_ROUTER = """
from fastapi_router_variants import RouterWrapper

parent = RouterWrapper(version=False)
router = RouterWrapper(version=False, parent=parent)


@router.get("/child")
def child() -> None: ...
"""
