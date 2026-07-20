import importlib
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from copy import copy
from dataclasses import dataclass
from typing import overload

from fastapi import APIRouter, FastAPI
from fastapi.routing import (
    APIRoute,
    APIWebSocketRoute,
    get_websocket_app,
    request_response,
    websocket_session,
)
from starlette.routing import BaseRoute

from fastapi_router_lazy.extractors.abc import AbstractRouteInfosExtractor
from fastapi_router_lazy.route_info import ExtractedRouteInfo

try:
    from fastapi.routing import iter_route_contexts
except ImportError:  # pragma: no cover - FastAPI < 0.139 flattens at include time
    iter_route_contexts = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def flatten_routes(routes: Sequence[BaseRoute]) -> list[BaseRoute]:
    """Expand FastAPI 0.139+ ``_IncludedRouter`` wrappers into their real routes.

    Since FastAPI 0.139, ``include_router`` appends a single opaque
    ``_IncludedRouter`` wrapper instead of the child
    ``APIRoute``/``APIWebSocketRoute`` objects. Left in a serving router, that
    wrapper lazily materialises and retains a full effective route tree the
    first time Starlette matches it, leaking hundreds of MB under load.
    Expanding it back to its underlying routes restores plain regex matching.

    A no-op on FastAPI 0.115→0.138 (routes are already flat) and on
    ``Mount``/sub-apps, which are surfaced untouched.
    """
    if iter_route_contexts is None:
        return list(routes)
    return [context.original_route for context in iter_route_contexts(routes)]


def reparent_route(route: BaseRoute, app: FastAPI | APIRouter) -> BaseRoute:
    """Bind a flattened route to the application that serves it.

    FastAPI 0.139 stores the effective dependency override provider on its
    included-router context instead of the underlying route. Flattening that
    context therefore requires rebuilding the route's ASGI handler with the
    serving application's provider.

    FastAPI routes are shallow-copied before rebinding so the same source
    router can be included safely in multiple applications. Non-FastAPI routes
    are returned unchanged.
    """
    if not isinstance(route, (APIRoute, APIWebSocketRoute)):
        return route

    route = copy(route)
    provider = app if isinstance(app, FastAPI) else app.dependency_overrides_provider

    if isinstance(route, APIRoute):
        route.dependency_overrides_provider = provider
        route.app = request_response(route.get_route_handler())
    else:
        route.app = websocket_session(
            get_websocket_app(
                dependant=route.dependant,
                dependency_overrides_provider=provider,
                embed_body_fields=route._embed_body_fields,
            )
        )

    return route


@dataclass(frozen=True)
class RouterLoaderMeta:
    module_name: str
    router_variable: str


RouterDecl = str | tuple[str, set[str] | None]


class LazyRouteRegistry(ABC):
    @classmethod
    @abstractmethod
    def register_lazy_routes(
        cls, module_route_infos: Iterable[ExtractedRouteInfo]
    ) -> None: ...


@dataclass
class LoadedRouter:
    router: APIRouter
    routes: list[BaseRoute]


class RouterLoader:
    """Mount routers on demand, one module (and router variable) at a time.

    Works with plain ``fastapi.APIRouter`` objects.
    """

    def __init__(
        self,
        extractor: AbstractRouteInfosExtractor,
        app: FastAPI | None = None,
        deployments: set[str] | None = None,
    ) -> None:
        self.extractor = extractor
        self.app = app
        self.deployments = deployments

    def filter_with_deployments(
        self, route_infos: list[ExtractedRouteInfo]
    ) -> list[ExtractedRouteInfo]:
        deployments = self.deployments
        if deployments is None:
            return route_infos
        return [
            route_info
            for route_info in route_infos
            if self._matches_deployment(route_info, deployments)
        ]

    def _matches_deployment(
        self, route_info: ExtractedRouteInfo, deployments: set[str]
    ) -> bool:
        deployment = route_info.deployment
        if deployment is False:
            return False
        if deployment is True:
            return True
        return (deployment or self.extractor.defaults.deployment) in deployments

    @classmethod
    def _include_router(
        cls,
        app: FastAPI | APIRouter | None,
        router: APIRouter,
    ) -> list[BaseRoute]:
        if app is None:
            app = APIRouter()

        routes_count = len(app.routes)
        app.include_router(router)
        flattened = [
            reparent_route(route, app)
            for route in flatten_routes(app.routes[routes_count:])
        ]
        app.routes[routes_count:] = flattened

        return list(flattened)

    def load_router(
        self, module_name: str, variables: str | set[str] | None = None
    ) -> list[LoadedRouter]:
        router_variables: set[str]
        if isinstance(variables, str):
            router_variables = {variables}
        elif isinstance(variables, Sequence):
            router_variables = set(variables)
        else:
            route_infos = self.extractor.extract_module_route_infos(module_name)
            route_infos = self.filter_with_deployments(route_infos)
            router_variables = {x.router_variable for x in route_infos}

        if not router_variables:
            logger.debug(
                f"Skipping module {module_name}: "
                f"no routes for deployments {self.deployments}"
            )
            return []

        try:
            imported_module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            logger.warning(f"Module {module_name} not found.")
            return []

        routers: list[LoadedRouter] = []

        for router_variable in router_variables:
            imported_router = getattr(imported_module, router_variable, None)
            if imported_router is None:
                logger.warning(
                    f"Router variable {router_variable!r} not found "
                    f"in module {module_name}."
                )
                continue
            routers.append(
                self._load_one(imported_router, module_name, router_variable)
            )

        return routers

    def _load_one(
        self, imported_router: object, module_name: str, router_variable: str
    ) -> LoadedRouter:
        router = self._resolve_router(imported_router)
        router._loader_meta = RouterLoaderMeta(  # type: ignore[attr-defined]
            module_name, router_variable
        )
        routes = self._include_router(self.app, router)
        return LoadedRouter(router, routes)

    def _resolve_router(self, imported_router: object) -> APIRouter:
        if isinstance(imported_router, APIRouter):
            return imported_router
        raise ValueError(
            "Router must be an instance of APIRouter, "
            f"got {type(imported_router).__name__}."
        )

    def load_routers(self, module_names: Iterable[str]) -> list[LoadedRouter]:
        loaded_routers: list[LoadedRouter] = []

        for module_name in module_names:
            loaded_routers.extend(self.load_router(module_name))

        return loaded_routers

    def load_router_decl(self, router_decl: RouterDecl) -> list[LoadedRouter]:
        if isinstance(router_decl, str):
            return self.load_router(router_decl)
        module_name, router_variable = router_decl
        return self.load_router(module_name, router_variable)

    def load_router_decls(
        self, router_decls: Iterable[RouterDecl]
    ) -> list[LoadedRouter]:
        loaded_routers: list[LoadedRouter] = []

        for router_decl in router_decls:
            loaded_routers.extend(self.load_router_decl(router_decl))

        return loaded_routers

    @overload
    def load(self, lazy_registry: type[LazyRouteRegistry]) -> None: ...

    @overload
    def load(self, lazy_registry: None = None) -> list[LoadedRouter]: ...

    @overload
    def load(
        self, lazy_registry: type[LazyRouteRegistry] | None = None
    ) -> list[LoadedRouter] | None: ...

    def load(
        self, lazy_registry: type[LazyRouteRegistry] | None = None
    ) -> list[LoadedRouter] | None:
        router_modules = tuple(self.extractor.scan_router_modules())

        if lazy_registry is None:
            return self.load_router_decls(router_modules)

        for router_module in router_modules:
            route_infos = self.extractor.extract_module_route_infos(router_module)
            route_infos = self.filter_with_deployments(route_infos)
            lazy_registry.register_lazy_routes(route_infos)

        return None
