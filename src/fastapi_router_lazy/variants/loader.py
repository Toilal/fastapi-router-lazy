"""Router loader for ``fastapi-router-variants`` ``RouterWrapper`` objects.

The core :class:`~fastapi_router_lazy.router_loader.RouterLoader` mounts plain
``fastapi.APIRouter`` objects only. :class:`VariantsRouterLoader` adds support
for ``RouterWrapper``: it unwraps the wrapper to its underlying ``APIRouter``
(``.base``) and includes it through every ``parent`` wrapper before reaching
the application.
"""

from typing import Any

from fastapi import APIRouter, FastAPI
from starlette.routing import BaseRoute

from fastapi_router_lazy.router_loader import (
    LoadedRouter,
    RouterLoader,
    RouterLoaderMeta,
)

try:
    from fastapi_router_variants import RouterWrapper
except ImportError as exc:  # pragma: no cover - exercised via the extra
    raise ImportError(
        "VariantsRouterLoader requires the optional 'variants' extra. "
        "Install it with: pip install fastapi-router-lazy[variants]"
    ) from exc


class VariantsRouterLoader(RouterLoader):
    """Mount plain ``APIRouter`` and ``RouterWrapper`` objects on demand."""

    def _load_one(
        self, imported_router: object, module_name: str, router_variable: str
    ) -> LoadedRouter:
        if not isinstance(imported_router, RouterWrapper):
            return super()._load_one(imported_router, module_name, router_variable)

        router = imported_router.base
        router._loader_meta = RouterLoaderMeta(  # type: ignore[attr-defined]
            module_name, router_variable
        )
        routes = self._include_with_parents(self.app, router, imported_router.parent)
        return LoadedRouter(router, routes)

    @classmethod
    def _include_with_parents(
        cls,
        app: FastAPI | APIRouter | None,
        router: APIRouter,
        parent_router: Any | None,
    ) -> list[BaseRoute]:
        if parent_router is None:
            return cls._include_router(app, router)

        routes_count = len(parent_router.base.routes)
        parent_router.include_router(router)
        included_routes = parent_router.base.routes[routes_count:]

        parent_routes = parent_router.base.routes
        try:
            # Include the parent router with the freshly added routes only.
            parent_router.base.routes = list(included_routes)
            return cls._include_with_parents(
                app, parent_router.base, parent_router.parent
            )
        finally:
            parent_router.base.routes = parent_routes
