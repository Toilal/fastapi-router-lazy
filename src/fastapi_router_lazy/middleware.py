"""ASGI middleware mounting lazy routers on their first matching request.

The registry mounts a lightweight *stub* route for every lazily-declared route.
On the first request that matches a stub, the middleware loads the real router
(via :class:`RouterLoader`), removes the consumed stubs, and lets the request
fall through to the freshly mounted route.
"""

import logging
from abc import abstractmethod
from collections.abc import Callable, Iterable

from fastapi import FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.routing import BaseRoute, Match, Route, WebSocketRoute
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fastapi_router_lazy.route_info import ExtractedRouteInfo
from fastapi_router_lazy.router_loader import LazyRouteRegistry, RouterLoader

logger = logging.getLogger(__name__)

LAZY_LOADING_ROUTER_HEADER = "x-fastapi-router-lazy-loading-router"
LAZY_LOADING_ROUTER_HEADER_BYTES = LAZY_LOADING_ROUTER_HEADER.encode("ascii")


class LazyMiddleware(LazyRouteRegistry):
    app: ASGIApp
    app_stub: FastAPI = FastAPI()
    _on_all_stubs_consumed: Callable[[], object] | None = None

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @abstractmethod
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None: ...

    @classmethod
    def get_stub_matching_route(
        cls, scope: Scope, match: Match = Match.FULL
    ) -> BaseRoute | None:
        for route in cls.app_stub.routes:
            route_match, _ = route.matches(scope)
            if route_match == match:
                return route
        return None

    @classmethod
    def remove_stub_routes(cls, route_name: str) -> list[BaseRoute]:
        routes_to_remove: list[BaseRoute] = [
            route
            for route in cls.app_stub.routes
            if isinstance(route, (Route, WebSocketRoute)) and route.name == route_name
        ]

        for route in routes_to_remove:
            logger.info(f"Removing lazy route stub {route}")
            cls.app_stub.routes.remove(route)

        has_remaining_stubs = any(
            isinstance(route, (Route, WebSocketRoute))
            and route.name
            and ":" in route.name
            for route in cls.app_stub.routes
        )
        if not has_remaining_stubs and cls._on_all_stubs_consumed is not None:
            cls._on_all_stubs_consumed()
            cls._on_all_stubs_consumed = None

        return routes_to_remove

    @classmethod
    def register_lazy_routes(
        cls, module_route_infos: Iterable[ExtractedRouteInfo]
    ) -> None:
        for route_info in module_route_infos:
            name = f"{route_info.router_module}:{route_info.router_variable}"

            if route_info.type == "http":

                @cls.app_stub.api_route(
                    route_info.path,
                    methods=(
                        list(route_info.methods)
                        if route_info.methods is not None
                        else None
                    ),
                    name=name,
                )
                def stub() -> None: ...

            elif route_info.type == "websocket":

                @cls.app_stub.websocket(route_info.path, name=name)
                def stub() -> None: ...

            logger.info(f"Including lazy route stub {route_info}")


def factory(router_loader: RouterLoader) -> type[LazyMiddleware]:
    class LazyMiddlewareInstance(LazyMiddleware):
        """ASGI middleware loading router modules on the first matching call."""

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http" and scope["type"] != "websocket":
                return await self.app(scope, receive, send)

            stub_route = self.get_stub_matching_route(scope)
            if isinstance(stub_route, (APIRoute, APIWebSocketRoute)):
                stub_route_name = stub_route.name
                stub_route_name_bytes = stub_route_name.encode("ascii")

                headers = scope.setdefault("headers", [])
                headers.append(
                    (LAZY_LOADING_ROUTER_HEADER_BYTES, stub_route_name_bytes)
                )

                module_name, router_variable = stub_route_name.split(":")
                router_loader.load_router(module_name, router_variable)

                self.remove_stub_routes(stub_route_name)

                original_send: Send = send

                async def send_override(message: Message) -> None:
                    if message["type"] == "http.response.start":
                        headers = message.setdefault("headers", [])
                        headers.append(
                            (LAZY_LOADING_ROUTER_HEADER_BYTES, stub_route_name_bytes)
                        )
                    await original_send(message)

                send = send_override

            return await self.app(scope, receive, send)

    return LazyMiddlewareInstance
