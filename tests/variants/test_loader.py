"""VariantsRouterLoader tests (require the optional 'variants' extra)."""

import pytest
from conftest import MakePackage
from fastapi import FastAPI
from starlette.testclient import TestClient

pytest.importorskip("fastapi_router_variants")

from fastapi_router_variants import RouterWrapper
from routers import PARENT_CHAIN_ROUTER, VARIANTS_ROUTER

from fastapi_router_lazy.variants import (
    RecordingRouteInfosExtractor,
    VariantsRouterLoader,
)


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
