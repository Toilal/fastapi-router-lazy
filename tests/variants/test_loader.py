"""VariantsRouterLoader tests (require the optional 'variants' extra)."""

import warnings

import pytest
from conftest import MakePackage
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from starlette.testclient import TestClient

pytest.importorskip("fastapi_router_variants")

from fastapi_router_variants import RouterWrapper
from routers import PARENT_CHAIN_ROUTER, VARIANTS_ROUTER

from fastapi_router_lazy import ExtractorDefaults, PlainRouteInfosExtractor
from fastapi_router_lazy.variants import (
    RecordingRouteInfosExtractor,
    VariantsRouterLoader,
)

PLAIN_ROUTER = """
from fastapi import APIRouter

router = APIRouter()


@router.get("/plain")
def plain() -> None: ...
"""


@pytest.fixture(autouse=True)
def _reset_router_wrapper() -> None:
    RouterWrapper.reset_defaults()
    RouterWrapper._route_recorder = None


def test_scan_and_load_end_to_end(make_package: MakePackage) -> None:
    package = make_package({"api.router": VARIANTS_ROUTER})
    extractor = RecordingRouteInfosExtractor(RouterWrapper, package)

    assert set(extractor.scan_router_modules()) == {f"{package}.api.router"}

    app = FastAPI()
    loader = VariantsRouterLoader(extractor, app)
    loader.load()

    client = TestClient(app)
    # Handlers return None -> 204; a success status proves the route is mounted.
    assert client.get("/users").status_code < 400
    assert client.get("/v1/items").status_code < 400
    assert client.get("/v2/items").status_code < 400


def test_load_router_with_parent_chain(make_package: MakePackage) -> None:
    package = make_package({"nested.router": PARENT_CHAIN_ROUTER})
    extractor = RecordingRouteInfosExtractor(RouterWrapper, package)

    app = FastAPI()
    VariantsRouterLoader(extractor, app).load()

    client = TestClient(app)
    # The child router is included through its parent wrapper chain.
    assert client.get("/child").status_code < 400


def test_mounts_plain_apirouter(make_package: MakePackage) -> None:
    package = make_package({"plain.router": PLAIN_ROUTER})
    extractor = PlainRouteInfosExtractor(ExtractorDefaults(), package)

    app = FastAPI()
    VariantsRouterLoader(extractor, app).load()

    client = TestClient(app)
    # A plain APIRouter (not a RouterWrapper) is delegated to the base loader.
    assert client.get("/plain").status_code < 400


def test_parent_wrapper_dependencies_run_once() -> None:
    calls: list[str] = []

    def parent_dependency() -> None:
        calls.append("parent")

    parent = RouterWrapper(version=False, dependencies=[Depends(parent_dependency)])
    wrapper = RouterWrapper(version=False, parent=parent)

    @wrapper.get("/child")
    def child() -> None: ...

    app = FastAPI()
    VariantsRouterLoader._include_with_parents(app, wrapper.base, wrapper.parent)

    assert TestClient(app).get("/child").status_code < 400
    assert calls == ["parent"]


def _api_paths(app: FastAPI) -> list[str]:
    return sorted(route.path for route in app.routes if isinstance(route, APIRoute))


def _duplicate_operation_id_warnings(app: FastAPI) -> list[str]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        app.openapi()
    return [
        str(warning.message)
        for warning in caught
        if "Duplicate Operation ID" in str(warning.message)
    ]


class TestChildLoadedBeforeAncestors:
    """Loading a child leaves no trace on its ancestors (#24)."""

    def test_parent_routes_are_left_unchanged(self) -> None:
        parent = RouterWrapper(version=False)
        child = RouterWrapper(version=False, parent=parent)

        @parent.get("/parent")
        def read_parent() -> None: ...

        @child.get("/child")
        def read_child() -> None: ...

        parent_routes = parent.base.routes
        before = list(parent_routes)
        VariantsRouterLoader._include_with_parents(FastAPI(), child.base, child.parent)

        assert parent.base.routes is parent_routes
        assert parent.base.routes == before

    def test_child_then_parent_serves_each_route_once(self) -> None:
        parent = RouterWrapper(version=False)
        child = RouterWrapper(version=False, parent=parent)

        @parent.get("/parent")
        def read_parent() -> None: ...

        @child.get("/child")
        def read_child() -> None: ...

        app = FastAPI()
        VariantsRouterLoader._include_with_parents(app, child.base, child.parent)
        VariantsRouterLoader._include_with_parents(app, parent.base, parent.parent)

        assert _api_paths(app) == ["/child", "/parent"]
        assert _duplicate_operation_id_warnings(app) == []

    def test_grandparent_chain_keeps_ancestors_and_dependencies(self) -> None:
        calls: list[str] = []

        def grand_dependency() -> None:
            calls.append("grand")

        def parent_dependency() -> None:
            calls.append("parent")

        grand = RouterWrapper(version=False, dependencies=[Depends(grand_dependency)])
        parent = RouterWrapper(
            version=False, parent=grand, dependencies=[Depends(parent_dependency)]
        )
        child = RouterWrapper(version=False, parent=parent)

        @grand.get("/grand")
        def read_grand() -> None: ...

        @parent.get("/parent")
        def read_parent() -> None: ...

        @child.get("/child")
        def read_child() -> None: ...

        before = {id(wrapper): list(wrapper.base.routes) for wrapper in (grand, parent)}
        app = FastAPI()
        VariantsRouterLoader._include_with_parents(app, child.base, child.parent)

        assert all(
            wrapper.base.routes == before[id(wrapper)] for wrapper in (grand, parent)
        )

        VariantsRouterLoader._include_with_parents(app, parent.base, parent.parent)
        VariantsRouterLoader._include_with_parents(app, grand.base, grand.parent)

        assert _api_paths(app) == ["/child", "/grand", "/parent"]
        assert _duplicate_operation_id_warnings(app) == []
        assert TestClient(app).get("/child").status_code < 400
        assert calls == ["grand", "parent"]
