import sys
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
