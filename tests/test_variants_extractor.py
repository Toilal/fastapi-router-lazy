"""Variant-aware extraction tests (require the optional 'variants' extra)."""

import pytest
from conftest import MakePackage
from fastapi import FastAPI
from starlette.testclient import TestClient

pytest.importorskip("fastapi_router_variants")

from fastapi_router_variants import RouterWrapper

from fastapi_router_lazy import RouterLoader
from fastapi_router_lazy.extractors.variants import (
    RecordingRouteInfosExtractor,
)

VARIANTS_ROUTER = """
from fastapi_router_variants import RouterWrapper

router = RouterWrapper(version=False)


@router.get("/users")
def list_users() -> None: ...


@router.get("/items", version=(1, 2))
def list_items() -> None: ...
"""

HIDDEN_ROUTER = """
from fastapi_router_variants import RouterWrapper

router = RouterWrapper(version=False, hidden=True, deployment="metrics")


@router.get("/metrics")
def metrics() -> None: ...
"""

PARENT_CHAIN_ROUTER = """
from fastapi_router_variants import RouterWrapper

parent = RouterWrapper(version=False)
router = RouterWrapper(version=False, parent=parent)


@router.get("/child")
def child() -> None: ...
"""


@pytest.fixture(autouse=True)
def _reset_router_wrapper() -> None:
    RouterWrapper.reset_defaults()
    RouterWrapper._route_recorder = None


def test_records_version_variants_without_mounting(
    make_package: MakePackage,
) -> None:
    package = make_package({"api.router": VARIANTS_ROUTER})
    extractor = RecordingRouteInfosExtractor(RouterWrapper, package)

    infos = extractor.extract_module_route_infos(f"{package}.api.router")

    paths = sorted(i.path for i in infos)
    assert paths == ["/users", "/v1/items", "/v2/items"]
    assert all(i.router_variable == "router" for i in infos)
    assert all(i.router_module == f"{package}.api.router" for i in infos)
    versions = {i.path: i.version for i in infos}
    assert versions["/v1/items"] == 1
    assert versions["/v2/items"] == 2


def test_extraction_does_not_leave_mounted_routes(
    make_package: MakePackage,
) -> None:
    import importlib

    package = make_package({"api.router": VARIANTS_ROUTER})
    extractor = RecordingRouteInfosExtractor(RouterWrapper, package)
    extractor.extract_module_route_infos(f"{package}.api.router")

    # A real import afterwards must build the routes normally (extraction
    # restored sys.modules).
    module = importlib.import_module(f"{package}.api.router")
    assert len(module.router.base.routes) == 3


def test_captures_hidden_and_deployment(make_package: MakePackage) -> None:
    package = make_package({"metrics.router": HIDDEN_ROUTER})
    extractor = RecordingRouteInfosExtractor(RouterWrapper, package)

    infos = extractor.extract_module_route_infos(f"{package}.metrics.router")

    assert len(infos) == 1
    assert infos[0].hidden is True
    assert infos[0].deployment == "metrics"


def test_scan_and_load_end_to_end(make_package: MakePackage) -> None:
    package = make_package({"api.router": VARIANTS_ROUTER})
    extractor = RecordingRouteInfosExtractor(RouterWrapper, package)

    assert set(extractor.scan_router_modules()) == {f"{package}.api.router"}

    app = FastAPI()
    loader = RouterLoader(extractor, app)
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
    RouterLoader(extractor, app).load()

    client = TestClient(app)
    # The child router is included through its parent wrapper chain.
    assert client.get("/child").status_code < 400
