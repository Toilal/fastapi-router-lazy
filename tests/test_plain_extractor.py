from conftest import MakePackage

from fastapi_router_lazy import (
    ExtractorDefaults,
    PlainRouteInfosExtractor,
    extract_routes_from_module,
)

USERS_ROUTER = """
from fastapi import APIRouter

router = APIRouter()


@router.get("/users")
def list_users() -> list[str]:
    return ["alice"]


@router.post("/users")
def create_user() -> None: ...
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

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(websocket) -> None: ...
"""


def _extractor(package: str) -> PlainRouteInfosExtractor:
    return PlainRouteInfosExtractor(ExtractorDefaults(), package)


class TestScanRouterModules:
    def test_scans_router_modules_recursively(self, make_package: MakePackage) -> None:
        package = make_package(
            {"users.router": USERS_ROUTER, "items.router": ITEMS_ROUTER}
        )
        extractor = _extractor(package)

        modules = set(extractor.scan_router_modules())
        assert modules == {f"{package}.users.router", f"{package}.items.router"}

    def test_custom_router_module_pattern(self, make_package: MakePackage) -> None:
        package = make_package({"users.routes": USERS_ROUTER})
        extractor = PlainRouteInfosExtractor(
            ExtractorDefaults(), package, router_module_pattern="routes.py"
        )

        modules = set(extractor.scan_router_modules())
        assert modules == {f"{package}.users.routes"}


class TestExtractModuleRouteInfos:
    def test_reads_http_routes(self, make_package: MakePackage) -> None:
        package = make_package({"users.router": USERS_ROUTER})
        extractor = _extractor(package)

        infos = extractor.extract_module_route_infos(f"{package}.users.router")

        paths_methods = sorted((i.path, i.methods) for i in infos)
        assert paths_methods == [
            ("/users", ("GET",)),
            ("/users", ("POST",)),
        ]
        assert all(i.type == "http" for i in infos)
        assert all(i.router_variable == "router" for i in infos)
        assert all(i.router_module == f"{package}.users.router" for i in infos)

    def test_reads_websocket_routes(self, make_package: MakePackage) -> None:
        package = make_package({"live.router": WS_ROUTER})
        extractor = _extractor(package)

        infos = extractor.extract_module_route_infos(f"{package}.live.router")

        assert len(infos) == 1
        assert infos[0].type == "websocket"
        assert infos[0].path == "/ws"
        assert infos[0].methods is None

    def test_filters_by_router_variable(self, make_package: MakePackage) -> None:
        package = make_package({"users.router": USERS_ROUTER})
        extractor = _extractor(package)

        infos = extractor.extract_module_route_infos(
            f"{package}.users.router", router_variables={"missing"}
        )
        assert infos == []

    def test_caches_extraction(self, make_package: MakePackage) -> None:
        package = make_package({"users.router": USERS_ROUTER})
        extractor = _extractor(package)

        first = extractor.extract_module_route_infos(f"{package}.users.router")
        second = extractor.extract_module_route_infos(f"{package}.users.router")
        assert first is second


def test_extract_routes_from_module_standalone(make_package: MakePackage) -> None:
    package = make_package({"items.router": ITEMS_ROUTER})
    infos = extract_routes_from_module(f"{package}.items.router")
    assert [i.path for i in infos] == ["/items"]
