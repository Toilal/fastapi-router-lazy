"""Default extractor: import a module and read routes off plain FastAPI routers.

This needs nothing but FastAPI. It imports the target module (running its route
handlers' import-time side effects), finds every ``APIRouter`` exposed as a
module attribute, and reads the already-built routes.
"""

import importlib
import logging
import sys

from fastapi import APIRouter
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.routing import Route, WebSocketRoute

from fastapi_router_lazy.extractors.abc import (
    DEFAULT_ROUTER_MODULE_PATTERN,
    AbstractRouteInfosExtractor,
    CachedExtractedRouteInfos,
    ExtractorDefaultsProtocol,
    InitializableExtractor,
)
from fastapi_router_lazy.route_info import ExtractedRouteInfo, RouteType

logger = logging.getLogger(__name__)


def _route_type(route: object) -> RouteType | None:
    if isinstance(route, (APIWebSocketRoute, WebSocketRoute)):
        return "websocket"
    if isinstance(route, (APIRoute, Route)):
        return "http"
    return None


def extract_routes_from_module(module_name: str) -> list[ExtractedRouteInfo]:
    """Import ``module_name`` and read the routes of its FastAPI routers."""
    module = importlib.import_module(module_name)

    route_infos: list[ExtractedRouteInfo] = []

    for variable, value in vars(module).items():
        if not isinstance(value, APIRouter):
            continue
        router = value

        for route in router.routes:
            route_type = _route_type(route)
            if route_type is None:
                continue

            methods: tuple[str, ...] | None = None
            if isinstance(route, (APIRoute, Route)) and route.methods:
                methods = tuple(sorted(route.methods))

            path = getattr(route, "path", None)
            if path is None:
                continue

            route_infos.append(
                ExtractedRouteInfo(
                    path=path,
                    type=route_type,
                    methods=methods,
                    router_module=module_name,
                    router_variable=variable,
                )
            )

    return route_infos


class PlainRouteInfosExtractor(AbstractRouteInfosExtractor, InitializableExtractor):
    """In-process extractor reading routes from plain FastAPI routers."""

    def __init__(
        self,
        defaults: ExtractorDefaultsProtocol,
        package_name: str,
        *,
        router_module_pattern: str = DEFAULT_ROUTER_MODULE_PATTERN,
    ) -> None:
        super().__init__(
            defaults, package_name, router_module_pattern=router_module_pattern
        )
        self.modules: dict[str, list[ExtractedRouteInfo]] = {}

    def preload_from_cache(self, cache: CachedExtractedRouteInfos) -> None:
        self.modules = {k: list(v) for k, v in cache.routes.items()}

    def reset(self, module_names: set[str] | None = None) -> None:
        if module_names is None:
            self.modules.clear()
        else:
            for module_name in module_names:
                self.modules.pop(module_name, None)

    def init(self) -> None:
        for module_name in self.scan_router_modules():
            if module_name not in self.modules:
                self.modules[module_name] = self._extract(module_name)

    def _extract(self, module_name: str) -> list[ExtractedRouteInfo]:
        sys.modules.pop(module_name, None)
        return extract_routes_from_module(module_name)

    def extract_module_route_infos(
        self,
        module_name: str,
        router_variables: set[str] | None = None,
    ) -> list[ExtractedRouteInfo]:
        route_infos = self.modules.get(module_name)
        if route_infos is None:
            route_infos = self._extract(module_name)
            self.modules[module_name] = route_infos

        if router_variables is None:
            return route_infos
        return [r for r in route_infos if r.router_variable in router_variables]
