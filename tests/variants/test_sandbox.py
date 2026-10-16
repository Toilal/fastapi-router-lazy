"""Variant-aware extraction in a child process (require the 'variants' extra)."""

import importlib
import logging
import sys

import pytest
from conftest import MakePackage

pytest.importorskip("fastapi_router_variants")

from fastapi_router_variants import RouterWrapper
from routers import (
    FAILING_ROUTER,
    HIDDEN_ROUTER,
    PARENT_CHAIN_ROUTER,
    REGISTERING_ROUTER,
    REGISTERING_SERVICE,
    REGISTRY,
    SUBCLASS_ROUTER,
    SUBCLASS_WRAPPER,
    UNRESOLVABLE_ORIGIN_ROUTER,
    VARIANTS_ROUTER,
)

from fastapi_router_lazy.route_info import ExtractedRouteInfo
from fastapi_router_lazy.variants import (
    RecordingRouteInfosExtractor,
    SandboxRecordingRouteInfosExtractor,
    record_routes_sandboxed,
)


@pytest.fixture(autouse=True)
def _reset_router_wrapper() -> None:
    RouterWrapper.reset_defaults()
    RouterWrapper._route_recorder = None


def _registering_package(make_package: MakePackage) -> str:
    package = make_package(
        {
            "registry": REGISTRY,
            "features.service": REGISTERING_SERVICE,
            "a.router": REGISTERING_ROUTER,
            "b.router": REGISTERING_ROUTER,
        }
    )
    # The application core holding the registry is loaded before extraction.
    importlib.import_module(f"{package}.registry")
    return package


def _sorted(route_infos: list[ExtractedRouteInfo]) -> list[ExtractedRouteInfo]:
    return sorted(
        route_infos, key=lambda r: (r.router_module, r.router_variable, r.path)
    )


def test_in_process_extraction_replays_import_side_effects(
    make_package: MakePackage,
) -> None:
    package = _registering_package(make_package)
    extractor = RecordingRouteInfosExtractor(RouterWrapper, package)

    with pytest.raises(ValueError, match="service is already registered"):
        extractor.init()


def test_isolates_import_side_effects_from_the_parent(
    make_package: MakePackage,
) -> None:
    package = _registering_package(make_package)
    extractor = SandboxRecordingRouteInfosExtractor(RouterWrapper, package)

    extractor.init()

    assert {
        module: [r.path for r in route_infos]
        for module, route_infos in extractor.modules.items()
    } == {f"{package}.a.router": ["/items"], f"{package}.b.router": ["/items"]}
    for module_name in extractor.modules:
        assert importlib.import_module(module_name).router.base.routes


def test_leaves_no_router_module_imported(make_package: MakePackage) -> None:
    package = make_package(
        {"api.router": VARIANTS_ROUTER, "metrics.router": HIDDEN_ROUTER}
    )
    extractor = SandboxRecordingRouteInfosExtractor(RouterWrapper, package)

    extractor.init()

    assert len(extractor.modules) == 2
    assert not [name for name in sys.modules if name.startswith(f"{package}.")]


def test_yields_the_same_route_infos_as_in_process_recording(
    make_package: MakePackage,
) -> None:
    package = make_package(
        {
            "api.router": VARIANTS_ROUTER,
            "metrics.router": HIDDEN_ROUTER,
            "chain.router": PARENT_CHAIN_ROUTER,
        }
    )
    in_process = RecordingRouteInfosExtractor(RouterWrapper, package)
    sandboxed = SandboxRecordingRouteInfosExtractor(RouterWrapper, package)

    in_process.init()
    sandboxed.init()

    assert set(sandboxed.modules) == set(in_process.modules)
    for module_name, route_infos in in_process.modules.items():
        assert route_infos
        assert _sorted(sandboxed.modules[module_name]) == _sorted(route_infos)


def test_resolves_routes_declared_through_a_wrapping_subclass(
    make_package: MakePackage,
) -> None:
    package = make_package(
        {"wrapping": SUBCLASS_WRAPPER, "location.router": SUBCLASS_ROUTER}
    )
    wrapper_class = importlib.import_module(f"{package}.wrapping").AppRouterWrapper
    extractor = SandboxRecordingRouteInfosExtractor(wrapper_class, package)

    infos = extractor.extract_module_route_infos(f"{package}.location.router")

    assert sorted(i.path for i in infos) == ["/v1/location", "/v2/location"]
    assert {(i.router_module, i.router_variable) for i in infos} == {
        (f"{package}.location.router", "router")
    }


def test_raises_with_the_child_error_output(make_package: MakePackage) -> None:
    package = make_package({"broken.router": FAILING_ROUTER})
    extractor = SandboxRecordingRouteInfosExtractor(RouterWrapper, package)

    with pytest.raises(RuntimeError, match="boom at import"):
        extractor.init()


def test_relays_the_child_warnings(
    make_package: MakePackage, caplog: pytest.LogCaptureFixture
) -> None:
    package = make_package({"orphan.router": UNRESOLVABLE_ORIGIN_ROUTER})
    extractor = SandboxRecordingRouteInfosExtractor(RouterWrapper, package)

    with caplog.at_level(logging.WARNING):
        extractor.init()

    assert extractor.modules == {f"{package}.orphan.router": []}
    assert "Could not resolve router origin for route /orphan" in caplog.text


def test_rejects_a_router_wrapper_class_the_child_cannot_import() -> None:
    class LocalRouterWrapper(RouterWrapper):
        pass

    with pytest.raises(ValueError, match="must be importable"):
        SandboxRecordingRouteInfosExtractor(LocalRouterWrapper, "anything")


def test_record_routes_sandboxed_empty() -> None:
    assert record_routes_sandboxed(RouterWrapper, []) == []
