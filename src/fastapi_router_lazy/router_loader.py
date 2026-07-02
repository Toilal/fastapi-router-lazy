import importlib
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, overload

from fastapi import APIRouter, FastAPI
from starlette.routing import BaseRoute

from fastapi_router_lazy.extractors.abc import AbstractRouteInfosExtractor
from fastapi_router_lazy.route_info import ExtractedRouteInfo

logger = logging.getLogger(__name__)


def _router_wrapper_cls() -> type[Any] | None:
    """Return ``RouterWrapper`` if the optional ``variants`` extra is present.

    Kept lazy so the core never imports ``fastapi_router_variants`` at module
    load time.
    """
    try:
        from fastapi_router_variants import RouterWrapper
    except ImportError:
        return None
    return RouterWrapper


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

    Works with plain ``fastapi.APIRouter`` objects. When the optional
    ``variants`` extra is installed, ``RouterWrapper`` objects are supported
    too, including their ``parent`` chains (the routes are included through
    every parent wrapper before reaching the application).
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
        if self.deployments is None:
            return route_infos
        return [
            route_info
            for route_info in route_infos
            if route_info.deployment is True
            or (route_info.deployment or self.extractor.defaults.deployment)
            in self.deployments
        ]

    @classmethod
    def _include_router(
        cls,
        app: FastAPI | APIRouter | None,
        router: APIRouter,
        parent_router: Any | None = None,
    ) -> list[BaseRoute]:
        if app is None:
            app = APIRouter()

        if parent_router is not None:
            routes_count = len(parent_router.base.routes)
            parent_router.include_router(router)
            included_routes = parent_router.base.routes[routes_count:]

            parent_routes = parent_router.base.routes
            try:
                # Include the parent router with the freshly added routes only.
                parent_router.base.routes = list(included_routes)
                return cls._include_router(
                    app, parent_router.base, parent_router.parent
                )
            finally:
                parent_router.base.routes = parent_routes

        routes_count = len(app.routes)
        app.include_router(router)
        included_routes = app.routes[routes_count:]

        return list(included_routes)

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

        router_wrapper_cls = _router_wrapper_cls()

        routers: list[LoadedRouter] = []

        for router_variable in router_variables:
            imported_router = getattr(imported_module, router_variable)
            parent_router: Any | None = None
            router: APIRouter

            if router_wrapper_cls is not None and isinstance(
                imported_router, router_wrapper_cls
            ):
                parent_router = imported_router.parent
                router = imported_router.base
            elif isinstance(imported_router, APIRouter):
                router = imported_router
            else:
                raise ValueError(
                    "Router must be an instance of APIRouter "
                    "(or RouterWrapper when the variants extra is installed)."
                )

            router._loader_meta = RouterLoaderMeta(  # type: ignore[attr-defined]
                module_name, router_variable
            )

            routes = self._include_router(self.app, router, parent_router)

            routers.append(LoadedRouter(router, routes))

        return routers

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
