import sys
from pathlib import Path

from conftest import MakePackage
from fastapi import FastAPI
from starlette.testclient import TestClient

from fastapi_router_lazy import (
    LAZY_LOADING_ROUTER_HEADER,
    CachedRouteInfosExtractor,
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


def _build(
    make_package: MakePackage, modules: dict[str, str]
) -> tuple[FastAPI, str, type[LazyMiddleware]]:
    package = make_package(modules)
    app = FastAPI()
    extractor = PlainRouteInfosExtractor(ExtractorDefaults(), package)
    loader = RouterLoader(extractor, app)
    middleware = lazy_middleware_factory(loader)
    app.add_middleware(middleware)
    loader.load(middleware)
    return app, package, middleware


def _stub_paths(middleware: type[LazyMiddleware]) -> set[str]:
    return {
        r.path
        for r in middleware.app_stub.routes
        if hasattr(r, "name") and ":" in (r.name or "")
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
    assert LAZY_LOADING_ROUTER_HEADER in response.headers
    # The stub was consumed once the router loaded.
    assert "/users" not in _stub_paths(middleware)


def test_second_request_still_served(make_package: MakePackage) -> None:
    app, _, _ = _build(make_package, {"users.router": USERS_ROUTER})
    client = TestClient(app)

    assert client.get("/users").status_code == 200
    # The stub was consumed; the real route keeps serving.
    assert client.get("/users").json() == ["alice"]


def test_only_matching_stub_is_consumed(make_package: MakePackage) -> None:
    app, _, middleware = _build(
        make_package, {"users.router": USERS_ROUTER, "items.router": ITEMS_ROUTER}
    )
    client = TestClient(app)

    client.get("/users")

    # Only the matching router loaded; the other stub is untouched.
    assert _stub_paths(middleware) == {"/items"}


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
    CachedRouteInfosExtractor._cache_file_cache.clear()

    # Build the cache (this imports the modules), then simulate a fresh process.
    route_infos_extractor(package, cache=True, cache_file=cache_file)
    CachedRouteInfosExtractor._cache_file_cache.clear()
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
