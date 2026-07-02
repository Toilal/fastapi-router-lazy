from conftest import MakePackage

from fastapi_router_lazy import (
    ExtractorDefaults,
    SandboxRouteInfosExtractor,
    extract_routes_sandboxed,
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


@router.post("/items")
def create_item() -> None: ...
"""


def test_extract_routes_sandboxed_empty() -> None:
    assert extract_routes_sandboxed([]) == []


def test_extract_routes_sandboxed(make_package: MakePackage) -> None:
    package = make_package({"users.router": USERS_ROUTER})
    infos = extract_routes_sandboxed([f"{package}.users.router"])
    assert [i.path for i in infos] == ["/users"]
    assert infos[0].router_variable == "router"


def test_sandbox_extractor_extract_module(make_package: MakePackage) -> None:
    package = make_package({"users.router": USERS_ROUTER})
    extractor = SandboxRouteInfosExtractor(ExtractorDefaults(), package)

    infos = extractor.extract_module_route_infos(f"{package}.users.router")
    assert [(i.path, i.methods) for i in infos] == [("/users", ("GET",))]


def test_sandbox_extractor_init_extracts_all(make_package: MakePackage) -> None:
    package = make_package({"users.router": USERS_ROUTER, "items.router": ITEMS_ROUTER})
    extractor = SandboxRouteInfosExtractor(ExtractorDefaults(), package)

    extractor.init()

    assert set(extractor.modules) == {
        f"{package}.users.router",
        f"{package}.items.router",
    }
