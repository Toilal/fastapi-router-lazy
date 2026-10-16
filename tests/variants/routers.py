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

SUBCLASS_WRAPPER = """
from collections.abc import Callable
from typing import Any

from fastapi_router_variants import RouterWrapper


class AppRouterWrapper(RouterWrapper):
    def get(self, path: Any, **kwargs: Any) -> Callable[..., Any]:
        def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
            super(AppRouterWrapper, self).get(path, **kwargs)(handler)
            return handler

        return decorator
"""

SUBCLASS_ROUTER = """
from ..wrapping import AppRouterWrapper

router = AppRouterWrapper(version=(1, 2))


@router.get("/location")
def location() -> None: ...
"""

REGISTRY = """
registered: set[str] = set()


def register(key: str) -> None:
    if key in registered:
        raise ValueError(f"{key} is already registered")
    registered.add(key)
"""

REGISTERING_SERVICE = """
from ..registry import register

register("service")
"""

REGISTERING_ROUTER = """
from fastapi_router_variants import RouterWrapper

from ..features import service  # noqa: F401

router = RouterWrapper(version=False)


@router.get("/items")
def list_items() -> None: ...
"""

FAILING_ROUTER = """
raise RuntimeError("boom at import")
"""

UNRESOLVABLE_ORIGIN_ROUTER = """
from fastapi_router_variants import RouterWrapper


def _declare() -> None:
    local = RouterWrapper(version=False)

    def handler() -> None: ...

    local.get("/orphan")(handler)


_declare()
"""
