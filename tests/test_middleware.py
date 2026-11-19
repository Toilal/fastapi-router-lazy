import json
import sys
from collections.abc import Iterator
from pathlib import Path

from conftest import MakePackage
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient

from fastapi_router_lazy import (
    LAZY_LOADING_ROUTER_HEADER,
    CachedRouteInfosExtractor,
    ExtractedRouteInfo,
    ExtractorDefaults,
    LazyMiddleware,
    LoadedRouter,
    PlainRouteInfosExtractor,
    RouterLoader,
    lazy_middleware_factory,
    route_infos_extractor,
)

USERS_ROUTER = """
from fastapi import APIRouter

router = APIRouter()


@router.get("/users")
def list_users() -> list[str]:
    return ["alice"]
"""

ITEMS_ROUTER = """
from fastapi import APIRouter

router = APIRouter()


@router.get("/items")
def list_items() -> list[str]:
    return ["book"]
"""

WS_ROUTER = """
from fastapi import APIRouter
from starlette.websockets import WebSocket

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_text("hi")
    await websocket.close()
"""


NESTED_ROUTER = """
from fastapi import APIRouter, Depends, Response

child = APIRouter()


@child.get("/items")
def list_items() -> list[str]:
    return ["book"]


def mark(response: Response) -> None:
    response.headers["x-include"] = "1"


router = APIRouter()
router.include_router(child, prefix="/sub", dependencies=[Depends(mark)])
"""


LOADING_HEADER_ROUTER = """
from typing import Annotated

from fastapi import APIRouter, Header, Request

router = APIRouter()


@router.get("/whoami")
def whoami(
    request: Request,
    loading_router: Annotated[str | None, Header(alias="HEADER_NAME")] = None,
) -> dict[str, object]:
    return {
        "dependency": loading_router,
        "all": request.headers.getlist("HEADER_NAME"),
    }
"""

LOADING_HEADER_WS_ROUTER = """
from fastapi import APIRouter
from starlette.websockets import WebSocket

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json(websocket.headers.getlist("HEADER_NAME"))
    await websocket.close()
"""


def _build(
    make_package: MakePackage,
    modules: dict[str, str],
    *,
    header_name: str = LAZY_LOADING_ROUTER_HEADER,
    response_header: bool = False,
) -> tuple[FastAPI, str, type[LazyMiddleware]]:
    package = make_package(modules)
    app = FastAPI()
    extractor = PlainRouteInfosExtractor(ExtractorDefaults(), package)
    loader = RouterLoader(extractor, app)
    middleware = lazy_middleware_factory(
        loader, header_name=header_name, response_header=response_header
    )
    app.add_middleware(middleware)
    loader.load(middleware)
    return app, package, middleware


def _stub_paths(middleware: type[LazyMiddleware]) -> set[str]:
    return {
        r.path
        for r in middleware.app_stub.routes
        if isinstance(r, (Route, WebSocketRoute)) and ":" in (r.name or "")
    }


def test_stub_registered_for_each_route(make_package: MakePackage) -> None:
    _, _, middleware = _build(
        make_package, {"users.router": USERS_ROUTER, "items.router": ITEMS_ROUTER}
    )
    assert _stub_paths(middleware) == {"/users", "/items"}


def test_first_request_lazily_mounts_router(make_package: MakePackage) -> None:
    app, _, middleware = _build(make_package, {"users.router": USERS_ROUTER})
    client = TestClient(app)

    response = client.get("/users")

    assert response.status_code == 200
    assert response.json() == ["alice"]
    # The stub was consumed once the router loaded.
    assert "/users" not in _stub_paths(middleware)


def test_second_request_still_served(make_package: MakePackage) -> None:
    app, _, _ = _build(make_package, {"users.router": USERS_ROUTER})
    client = TestClient(app)

    assert client.get("/users").status_code == 200
    # The stub was consumed; the real route keeps serving.
    assert client.get("/users").json() == ["alice"]


def test_nested_include_route_lazily_mounted(make_package: MakePackage) -> None:
    app, _, middleware = _build(make_package, {"nested.router": NESTED_ROUTER})
    client = TestClient(app)

    assert "/sub/items" in _stub_paths(middleware)
    response = client.get("/sub/items")

    assert response.json() == ["book"]
    assert response.headers["x-include"] == "1"
    assert client.get("/sub/items").headers["x-include"] == "1"


def test_only_matching_stub_is_consumed(make_package: MakePackage) -> None:
    app, _, middleware = _build(
        make_package, {"users.router": USERS_ROUTER, "items.router": ITEMS_ROUTER}
    )
    client = TestClient(app)

    client.get("/users")

    # Only the matching router loaded; the other stub is untouched.
    assert _stub_paths(middleware) == {"/items"}


def _loading_header_router(header_name: str = LAZY_LOADING_ROUTER_HEADER) -> str:
    return LOADING_HEADER_ROUTER.replace("HEADER_NAME", header_name)


def test_loading_request_carries_the_loaded_router(make_package: MakePackage) -> None:
    app, package, _ = _build(make_package, {"me.router": _loading_header_router()})
    client = TestClient(app)

    response = client.get("/whoami")

    loaded = f"{package}.me.router:router"
    assert response.json() == {"dependency": loaded, "all": [loaded]}
    assert LAZY_LOADING_ROUTER_HEADER not in response.headers


def test_client_header_never_reaches_the_application(
    make_package: MakePackage,
) -> None:
    app, package, _ = _build(make_package, {"me.router": _loading_header_router()})
    client = TestClient(app)
    spoofed = {LAZY_LOADING_ROUTER_HEADER: "spoofed:router"}

    loading = client.get("/whoami", headers=spoofed)
    loaded = client.get("/whoami", headers=spoofed)

    expected = f"{package}.me.router:router"
    assert loading.json() == {"dependency": expected, "all": [expected]}
    assert loaded.json() == {"dependency": None, "all": []}
    assert LAZY_LOADING_ROUTER_HEADER not in loaded.headers


def test_websocket_loading_scope_carries_the_loaded_router(
    make_package: MakePackage,
) -> None:
    app, package, _ = _build(
        make_package,
        {
            "live.router": LOADING_HEADER_WS_ROUTER.replace(
                "HEADER_NAME", LAZY_LOADING_ROUTER_HEADER
            )
        },
    )
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == [f"{package}.live.router:router"]


def test_header_name_is_configurable(make_package: MakePackage) -> None:
    app, package, _ = _build(
        make_package,
        {"me.router": _loading_header_router("x-app-loading-router")},
        header_name="X-App-Loading-Router",
        response_header=True,
    )
    client = TestClient(app)

    response = client.get("/whoami")

    loaded = f"{package}.me.router:router"
    assert response.json() == {"dependency": loaded, "all": [loaded]}
    assert response.headers["x-app-loading-router"] == loaded
    assert LAZY_LOADING_ROUTER_HEADER not in response.headers


def test_response_header_is_opt_in(make_package: MakePackage) -> None:
    app, package, _ = _build(
        make_package, {"users.router": USERS_ROUTER}, response_header=True
    )
    client = TestClient(app)

    loading = client.get("/users")
    loaded = client.get("/users")

    assert (
        loading.headers[LAZY_LOADING_ROUTER_HEADER] == f"{package}.users.router:router"
    )
    assert LAZY_LOADING_ROUTER_HEADER not in loaded.headers


def test_methods_none_stub_matches_any_verb(make_package: MakePackage) -> None:
    package = make_package({"users.router": USERS_ROUTER})
    extractor = PlainRouteInfosExtractor(ExtractorDefaults(), package)
    middleware = lazy_middleware_factory(RouterLoader(extractor, FastAPI()))

    middleware.register_lazy_routes(
        [
            ExtractedRouteInfo(
                path="/any",
                methods=None,
                type="http",
                router_module="m",
                router_variable="router",
            )
        ]
    )

    stub = next(
        r
        for r in middleware.app_stub.routes
        if isinstance(r, APIRoute) and r.name == "m:router"
    )
    assert stub.methods is not None
    assert {"GET", "POST", "PUT", "PATCH", "DELETE"} <= stub.methods


def test_websocket_route_lazily_mounted(make_package: MakePackage) -> None:
    app, _, middleware = _build(make_package, {"live.router": WS_ROUTER})
    assert "/ws" in _stub_paths(middleware)

    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_text() == "hi"

    assert "/ws" not in _stub_paths(middleware)


def test_on_all_stubs_consumed_callback(make_package: MakePackage) -> None:
    app, _, middleware = _build(make_package, {"users.router": USERS_ROUTER})
    consumed: list[bool] = []
    middleware._on_all_stubs_consumed = lambda: consumed.append(True)

    client = TestClient(app)
    client.get("/users")

    assert consumed == [True]


def test_two_apps_have_independent_stub_tables(make_package: MakePackage) -> None:
    app_a, _, mw_a = _build(make_package, {"users.router": USERS_ROUTER})
    _, _, mw_b = _build(make_package, {"items.router": ITEMS_ROUTER})

    assert mw_a.app_stub is not mw_b.app_stub
    assert _stub_paths(mw_a) == {"/users"}
    assert _stub_paths(mw_b) == {"/items"}

    # Consuming a stub in app A leaves app B's table untouched.
    TestClient(app_a).get("/users")

    assert _stub_paths(mw_a) == set()
    assert _stub_paths(mw_b) == {"/items"}


def test_on_all_stubs_consumed_callback_is_scoped_per_app(
    make_package: MakePackage,
) -> None:
    app_a, _, mw_a = _build(make_package, {"users.router": USERS_ROUTER})
    _, _, mw_b = _build(make_package, {"items.router": ITEMS_ROUTER})
    fired: list[str] = []
    mw_a._on_all_stubs_consumed = lambda: fired.append("a")
    mw_b._on_all_stubs_consumed = lambda: fired.append("b")

    TestClient(app_a).get("/users")

    assert fired == ["a"]


def test_plain_default_imports_modules_at_load(make_package: MakePackage) -> None:
    """The default (Plain) extractor imports every module at load() time.

    Negative mirror of test_modules_imported_only_on_first_request_with_cache:
    Plain reads routes by importing the module, so load() imports it before any
    request — the deferred-import gain requires a warm cache (or Sandbox).
    """
    package = make_package({"users.router": USERS_ROUTER})
    for name in list(sys.modules):
        if name == package or name.startswith(f"{package}."):
            del sys.modules[name]

    app = FastAPI()
    extractor = route_infos_extractor(package)  # default = Plain, no cache
    loader = RouterLoader(extractor, app)
    middleware = lazy_middleware_factory(loader)
    app.add_middleware(middleware)

    assert f"{package}.users.router" not in sys.modules

    loader.load(middleware)

    # No request made, yet Plain already imported the module to read its routes.
    assert f"{package}.users.router" in sys.modules


def test_modules_imported_only_on_first_request_with_cache(
    make_package: MakePackage, tmp_path: Path
) -> None:
    """With a valid cache, no router module is imported until it is requested."""
    package = make_package({"users.router": USERS_ROUTER, "items.router": ITEMS_ROUTER})
    cache_file = tmp_path / "routes.json"
    CachedRouteInfosExtractor.clear_file_cache()

    # Build the cache (this imports the modules), then simulate a fresh process.
    route_infos_extractor(package, cache=True, cache_file=cache_file)
    CachedRouteInfosExtractor.clear_file_cache()
    for name in list(sys.modules):
        if name == package or name.startswith(f"{package}."):
            del sys.modules[name]

    app = FastAPI()
    extractor = route_infos_extractor(package, cache=True, cache_file=cache_file)
    loader = RouterLoader(extractor, app)
    middleware = lazy_middleware_factory(loader)
    app.add_middleware(middleware)
    loader.load(middleware)

    # Cache hit: nothing imported yet.
    assert f"{package}.users.router" not in sys.modules
    assert f"{package}.items.router" not in sys.modules

    client = TestClient(app)
    client.get("/users")

    assert f"{package}.users.router" in sys.modules
    assert f"{package}.items.router" not in sys.modules


def _item_router(path: str, served_by: str) -> str:
    return f"""
from fastapi import APIRouter

router = APIRouter()


@router.get("{path}")
def endpoint() -> str:
    return "{served_by}"
"""


SPECIAL_THEN_PARAMETERIZED_ROUTER = """
from fastapi import APIRouter

router = APIRouter()


@router.get("/items/special")
def special() -> str:
    return "special"


@router.get("/items/{item_id}")
def item(item_id: str) -> str:
    return f"item {item_id}"
"""

SHADOWING_MODULES = {
    "a_special.router": _item_router("/items/special", "special"),
    "b_items.router": _item_router("/items/{item_id}", "item"),
}


def _eager_responses(make_package: MakePackage, paths: list[str]) -> list[str]:
    package = make_package(SHADOWING_MODULES)
    app = FastAPI()
    RouterLoader(PlainRouteInfosExtractor(ExtractorDefaults(), package), app).load()
    client = TestClient(app)
    return [client.get(path).json() for path in paths]


def test_explicit_router_list_keeps_its_order(make_package: MakePackage) -> None:
    package = make_package(SHADOWING_MODULES)
    app = FastAPI()
    loader = RouterLoader(PlainRouteInfosExtractor(ExtractorDefaults(), package), app)

    loader.load_routers([f"{package}.b_items.router", f"{package}.a_special.router"])

    assert TestClient(app).get("/items/special").json() == "item"


def test_explicit_router_list_keeps_its_order_after_lazy_registration(
    make_package: MakePackage,
) -> None:
    package = make_package(SHADOWING_MODULES)
    explicit_order = [f"{package}.b_items.router", f"{package}.a_special.router"]

    for load in ("load_routers", "load_router_decls"):
        app = FastAPI()
        loader = RouterLoader(
            PlainRouteInfosExtractor(ExtractorDefaults(), package), app
        )
        middleware = lazy_middleware_factory(loader)
        loader.load(middleware)

        getattr(loader, load)(explicit_order)

        paths = [route.path for route in app.routes if isinstance(route, APIRoute)]
        assert paths.index("/items/{item_id}") < paths.index("/items/special"), load


def test_routers_an_override_loads_during_a_lazy_load_keep_their_order(
    make_package: MakePackage,
) -> None:
    package = make_package({**SHADOWING_MODULES, "c.router": _item_router("/c", "c")})
    explicit_order = [f"{package}.b_items.router", f"{package}.a_special.router"]

    class ExplicitLoadingRouterLoader(RouterLoader):
        def load_router(
            self, module_name: str, variables: str | set[str] | None = None
        ) -> list[LoadedRouter]:
            if module_name == f"{package}.c.router":
                self.load_routers(explicit_order)
            return super().load_router(module_name, variables)

    app = FastAPI()
    loader = ExplicitLoadingRouterLoader(
        PlainRouteInfosExtractor(ExtractorDefaults(), package), app
    )
    middleware = lazy_middleware_factory(loader)
    app.add_middleware(middleware)
    loader.load(middleware)

    assert TestClient(app).get("/c").json() == "c"

    paths = [route.path for route in app.routes if isinstance(route, APIRoute)]
    assert paths.index("/items/{item_id}") < paths.index("/items/special")


def test_explicit_list_answering_a_lazy_request_keeps_its_order(
    make_package: MakePackage,
) -> None:
    package = make_package(SHADOWING_MODULES)
    special_module = f"{package}.a_special.router"
    explicit_order = [f"{package}.b_items.router", special_module]

    class ExplicitListRouterLoader(RouterLoader):
        def load_router(
            self, module_name: str, variables: str | set[str] | None = None
        ) -> list[LoadedRouter]:
            if module_name == special_module and variables is not None:
                return self.load_routers(explicit_order)
            return super().load_router(module_name, variables)

    for earlier_requests in ([], ["/items/1"]):
        app = FastAPI()
        loader = ExplicitListRouterLoader(
            PlainRouteInfosExtractor(ExtractorDefaults(), package), app
        )
        middleware = lazy_middleware_factory(loader)
        app.add_middleware(middleware)
        loader.load(middleware)
        client = TestClient(app)
        for path in earlier_requests:
            client.get(path)

        assert client.get("/items/special").json() == "item", earlier_requests


SPECIAL_WITH_HELPER_ROUTER = """
from fastapi import APIRouter

router = APIRouter()
helper = APIRouter()


@router.get("/items/special")
def special() -> str:
    return "special"


@helper.get("/helper")
def helper_endpoint() -> str:
    return "helper"
"""


def test_override_loading_another_router_of_the_module_first_keeps_placement(
    make_package: MakePackage,
) -> None:
    package = make_package(
        {
            "a_special.router": SPECIAL_WITH_HELPER_ROUTER,
            "b_items.router": SHADOWING_MODULES["b_items.router"],
        }
    )
    special_module = f"{package}.a_special.router"

    class HelperFirstRouterLoader(RouterLoader):
        def load_router(
            self, module_name: str, variables: str | set[str] | None = None
        ) -> list[LoadedRouter]:
            if module_name == special_module and variables == "router":
                super().load_router(module_name, "helper")
            return super().load_router(module_name, variables)

    for earlier_requests in ([], ["/items/1"]):
        app = FastAPI()
        loader = HelperFirstRouterLoader(
            PlainRouteInfosExtractor(ExtractorDefaults(), package), app
        )
        middleware = lazy_middleware_factory(loader)
        app.add_middleware(middleware)
        loader.load(middleware)
        client = TestClient(app)
        for path in earlier_requests:
            client.get(path)

        assert client.get("/items/special").json() == "special", earlier_requests


def test_route_added_by_an_override_after_mounting_is_kept(
    make_package: MakePackage,
) -> None:
    package = make_package(
        {"a.router": _item_router("/a", "a"), "b.router": _item_router("/b", "b")}
    )

    class HealthRouteRouterLoader(RouterLoader):
        def _load_one(
            self, imported_router: object, module_name: str, router_variable: str
        ) -> LoadedRouter:
            loaded = super()._load_one(imported_router, module_name, router_variable)
            assert self.app is not None
            self.app.add_api_route(f"/health/{module_name}", lambda: "ok")
            return loaded

    app = FastAPI()
    loader = HealthRouteRouterLoader(
        PlainRouteInfosExtractor(ExtractorDefaults(), package), app
    )
    middleware = lazy_middleware_factory(loader)
    app.add_middleware(middleware)
    loader.load(middleware)
    client = TestClient(app)

    client.get("/b")
    client.get("/a")

    paths = [route.path for route in app.routes if isinstance(route, APIRoute)]
    assert paths.count("/a") == 1
    assert paths.index("/a") < paths.index("/b")
    for module in ("a", "b"):
        assert client.get(f"/health/{package}.{module}.router").json() == "ok"


def test_nested_lazy_load_keeps_the_enclosing_request(
    make_package: MakePackage,
) -> None:
    package = make_package({**SHADOWING_MODULES, "c.router": _item_router("/c", "c")})
    special_module = f"{package}.a_special.router"
    c_module = f"{package}.c.router"

    class NestedLazyRouterLoader(RouterLoader):
        nested_loaded = False

        def load_router(
            self, module_name: str, variables: str | set[str] | None = None
        ) -> list[LoadedRouter]:
            if module_name == special_module and not self.nested_loaded:
                self.nested_loaded = True
                self.load_router_lazily(c_module, "router")
            return super().load_router(module_name, variables)

    for earlier_requests in ([], ["/items/1"]):
        app = FastAPI()
        loader = NestedLazyRouterLoader(
            PlainRouteInfosExtractor(ExtractorDefaults(), package), app
        )
        middleware = lazy_middleware_factory(loader)
        app.add_middleware(middleware)
        loader.load(middleware)
        client = TestClient(app)
        for path in earlier_requests:
            client.get(path)

        assert client.get("/items/special").json() == "special", earlier_requests


class ReverseScanExtractor(PlainRouteInfosExtractor):
    def scan_router_modules(self) -> Iterator[str]:
        yield from sorted(super().scan_router_modules(), reverse=True)


def test_extractor_scan_order_does_not_change_route_resolution(
    make_package: MakePackage,
) -> None:
    package = make_package(SHADOWING_MODULES)

    lazy_app = FastAPI()
    lazy_loader = RouterLoader(
        ReverseScanExtractor(ExtractorDefaults(), package), lazy_app
    )
    middleware = lazy_middleware_factory(lazy_loader)
    lazy_app.add_middleware(middleware)
    lazy_loader.load(middleware)
    lazy_client = TestClient(lazy_app)
    lazy = [lazy_client.get("/items/special").json() for _ in range(2)]

    eager_app = FastAPI()
    RouterLoader(ReverseScanExtractor(ExtractorDefaults(), package), eager_app).load()
    eager = TestClient(eager_app).get("/items/special").json()

    assert lazy == ["special", "special"]
    assert eager == "special"


def test_router_loaded_late_is_not_shadowed_by_a_greater_router(
    make_package: MakePackage,
) -> None:
    app, _, _ = _build(make_package, SHADOWING_MODULES)
    client = TestClient(app)

    assert client.get("/items/1").json() == "item"
    assert client.get("/items/special").json() == "special"


def test_routes_resolve_alike_whatever_the_loading_order(
    make_package: MakePackage,
) -> None:
    app, _, _ = _build(make_package, SHADOWING_MODULES)
    client = TestClient(app)

    lazy = [client.get("/items/special").json(), client.get("/items/1").json()]

    assert lazy == ["special", "item"]
    assert lazy == _eager_responses(make_package, ["/items/special", "/items/1"])


TWO_VARIABLES_ROUTER = """
from fastapi import APIRouter

z_router = APIRouter()
a_router = APIRouter()


@z_router.get("/items/{item_id}")
def item(item_id: str) -> str:
    return "z_router"


@a_router.get("/items/special")
def special() -> str:
    return "a_router"
"""


def test_router_variables_of_a_module_resolve_alike_in_both_modes(
    make_package: MakePackage,
) -> None:
    modules = {"items.router": TWO_VARIABLES_ROUTER}
    app, _, _ = _build(make_package, modules)
    client = TestClient(app)

    lazy = [client.get("/items/special").json(), client.get("/items/special").json()]

    eager_package = make_package(modules)
    eager_app = FastAPI()
    RouterLoader(
        PlainRouteInfosExtractor(ExtractorDefaults(), eager_package), eager_app
    ).load()
    eager = TestClient(eager_app).get("/items/special").json()

    assert lazy == ["a_router", "a_router"]
    assert eager == "a_router"


def test_router_loads_after_a_greater_router_was_removed_from_the_app(
    make_package: MakePackage,
) -> None:
    app, _, _ = _build(
        make_package,
        {"a.router": _item_router("/a", "a"), "b.router": _item_router("/b", "b")},
    )
    client = TestClient(app)
    client.get("/b")
    app.router.routes[:] = [
        route for route in app.routes if getattr(route, "path", None) != "/b"
    ]

    assert client.get("/a").json() == "a"


def _write_manifest_in_reverse_name_order(cache_file: Path) -> list[str]:
    manifest = json.loads(cache_file.read_text())
    for field in ("routes", "router_checksums"):
        manifest[field] = dict(sorted(manifest[field].items(), reverse=True))
    cache_file.write_text(json.dumps(manifest, indent=2))
    return list(manifest["routes"])


def test_unsorted_manifest_serves_every_route_in_canonical_order(
    make_package: MakePackage, tmp_path: Path
) -> None:
    package = make_package({**SHADOWING_MODULES, "users.router": USERS_ROUTER})
    cache_file = tmp_path / "routes.json"
    CachedRouteInfosExtractor.clear_file_cache()
    route_infos_extractor(package, cache=True, cache_file=cache_file)
    manifest_modules = _write_manifest_in_reverse_name_order(cache_file)
    assert manifest_modules != sorted(manifest_modules)

    for requests in (
        ["/items/1", "/items/special", "/users"],
        ["/users", "/items/special", "/items/1"],
    ):
        CachedRouteInfosExtractor.clear_file_cache()
        app = FastAPI()
        extractor = route_infos_extractor(package, cache=True, cache_file=cache_file)
        assert isinstance(extractor, CachedRouteInfosExtractor)
        loader = RouterLoader(extractor, app)
        middleware = lazy_middleware_factory(loader)
        app.add_middleware(middleware)
        loader.load(middleware)
        client = TestClient(app)

        responses = {path: client.get(path).json() for path in requests}

        assert responses == {
            "/items/1": "item",
            "/items/special": "special",
            "/users": ["alice"],
        }
    assert list(json.loads(cache_file.read_text())["routes"]) == manifest_modules


def test_declaration_order_within_a_module_is_kept(make_package: MakePackage) -> None:
    app, _, _ = _build(
        make_package, {"items.router": SPECIAL_THEN_PARAMETERIZED_ROUTER}
    )
    client = TestClient(app)

    assert client.get("/items/1").json() == "item 1"
    assert client.get("/items/special").json() == "special"


def test_loaded_routers_are_kept_in_module_name_order(
    make_package: MakePackage,
) -> None:
    app, _, _ = _build(
        make_package,
        {
            "a.router": _item_router("/a", "a"),
            "b.router": _item_router("/b", "b"),
            "c.router": _item_router("/c", "c"),
        },
    )

    @app.get("/own")
    def own() -> str:
        return "own"

    client = TestClient(app)
    for path in ("/c", "/a", "/b"):
        client.get(path)

    paths = [route.path for route in app.routes if isinstance(route, APIRoute)]
    assert paths.index("/own") < paths.index("/a")
    assert [path for path in paths if path in {"/a", "/b", "/c"}] == ["/a", "/b", "/c"]
