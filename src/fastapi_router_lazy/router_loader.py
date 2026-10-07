import importlib
import inspect
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from copy import copy
from dataclasses import dataclass
from typing import Any, cast, overload

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

logger = logging.getLogger(__name__)

_API_ROUTE_ACCEPTS_STRICT_CONTENT_TYPE = (
    "strict_content_type" in inspect.signature(APIRoute.__init__).parameters
)


def _is_included_router(route: BaseRoute) -> bool:
    return getattr(route, "original_router", None) is not None


def _has_low_priority_routes(router: Any) -> bool:
    """Whether a router tree serves routes FastAPI only matches through includes.

    ``APIRouter.frontend()`` registers low-priority routes that the parent
    reaches through ``_IncludedRouter.effective_low_priority_routes()`` only, so
    unwrapping such an include would stop serving them.
    """
    if getattr(router, "_low_priority_routes", None):
        return True
    return any(
        _has_low_priority_routes(cast("Any", route).original_router)
        for route in router.routes
        if _is_included_router(route)
    )


def _materialize_api_route(context: Any) -> APIRoute:
    kwargs: dict[str, Any] = {}
    if _API_ROUTE_ACCEPTS_STRICT_CONTENT_TYPE:
        kwargs["strict_content_type"] = context.strict_content_type
    route_class = cast("type[APIRoute]", type(context.original_route))
    return route_class(
        context.path,
        context.endpoint,
        response_model=context.response_model,
        status_code=context.status_code,
        tags=context.tags,
        dependencies=context.dependencies,
        summary=context.summary,
        description=context.description,
        response_description=context.response_description,
        responses=context.responses,
        deprecated=context.deprecated,
        name=context.name,
        methods=context.methods,
        operation_id=context.operation_id,
        response_model_include=context.response_model_include,
        response_model_exclude=context.response_model_exclude,
        response_model_by_alias=context.response_model_by_alias,
        response_model_exclude_unset=context.response_model_exclude_unset,
        response_model_exclude_defaults=context.response_model_exclude_defaults,
        response_model_exclude_none=context.response_model_exclude_none,
        include_in_schema=context.include_in_schema,
        response_class=context.response_class,
        dependency_overrides_provider=context.dependency_overrides_provider,
        callbacks=context.callbacks,
        openapi_extra=context.openapi_extra,
        generate_unique_id_function=context.generate_unique_id_function,
        **kwargs,
    )


def _materialize_route_context(context: Any) -> BaseRoute:
    if isinstance(context.original_route, APIRoute):
        return _materialize_api_route(context)
    return cast("BaseRoute", context.starlette_route)


def flatten_routes(routes: Sequence[BaseRoute]) -> list[BaseRoute]:
    """Replace FastAPI 0.137+ ``_IncludedRouter`` wrappers with effective routes.

    Since FastAPI 0.137, ``include_router`` appends a single opaque
    ``_IncludedRouter`` wrapper instead of copying the child routes. Its include
    context (prefix, tags, dependencies, responses, ``include_in_schema``,
    response class, unique id function, content-type strictness, dependency
    override provider) is only applied when FastAPI resolves a route, and the
    wrapper retains a full effective route tree the first time Starlette
    matches it, leaking hundreds of MB under load.

    Every route reachable through such a wrapper, nested includes included, is
    rebuilt with that effective context, the way FastAPI <= 0.136
    ``include_router`` copied routes eagerly. The rebuilt routes are new
    objects bound to the override provider of the router the include was made
    on, so the included router's own routes are never mutated.

    Includes whose router tree holds ``APIRouter.frontend()`` routes are kept
    as-is, since FastAPI only serves those through the wrapper. Other routes
    are returned unchanged, so on FastAPI <= 0.136 the result equals ``routes``.
    """
    flattened: list[BaseRoute] = []
    for route in routes:
        included = cast("Any", route)
        if _is_included_router(route) and not _has_low_priority_routes(
            included.original_router
        ):
            # A copy keeps FastAPI's effective-context cache off the caller's
            # wrapper, which may outlive this call (a module's own router).
            flattened.extend(
                _materialize_route_context(context)
                for context in copy(included).effective_route_contexts()
            )
        else:
            flattened.append(route)
    return flattened


def reparent_route(route: BaseRoute, app: FastAPI | APIRouter) -> BaseRoute:
    """Bind a route to the application that serves it.

    Rebuilds the route's ASGI handler with the dependency override provider of
    ``app``. Routes returned by ``flatten_routes`` are already bound to the
    router their include was made on; this rebinds a route to another one.

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
        flattened = flatten_routes(app.routes[routes_count:])
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
