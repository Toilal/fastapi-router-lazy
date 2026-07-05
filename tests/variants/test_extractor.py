"""Variant-aware extraction tests (require the optional 'variants' extra)."""

import pytest
from conftest import MakePackage

pytest.importorskip("fastapi_router_variants")

from fastapi_router_variants import RouterWrapper
from routers import HIDDEN_ROUTER, VARIANTS_ROUTER

from fastapi_router_lazy.variants import RecordingRouteInfosExtractor


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
