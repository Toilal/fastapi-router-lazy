from pathlib import Path

from conftest import MakePackage

from fastapi_router_lazy import (
    CachedRouteInfosExtractor,
    PlainRouteInfosExtractor,
    route_infos_extractor,
)

USERS_ROUTER = """
from fastapi import APIRouter

router = APIRouter()


@router.get("/users")
def list_users() -> list[str]:
    return ["alice"]
"""


def test_factory_defaults_to_plain(make_package: MakePackage) -> None:
    package = make_package({"users.router": USERS_ROUTER})
    extractor = route_infos_extractor(package)
    assert isinstance(extractor, PlainRouteInfosExtractor)


def test_factory_wraps_in_cache(make_package: MakePackage, tmp_path: Path) -> None:
    package = make_package({"users.router": USERS_ROUTER})
    CachedRouteInfosExtractor.clear_file_cache()

    extractor = route_infos_extractor(
        package, cache=True, cache_file=tmp_path / "routes.json"
    )

    assert isinstance(extractor, CachedRouteInfosExtractor)
    infos = extractor.extract_module_route_infos(f"{package}.users.router")
    assert [i.path for i in infos] == ["/users"]


def test_factory_custom_pattern(make_package: MakePackage) -> None:
    package = make_package({"users.routes": USERS_ROUTER})
    extractor = route_infos_extractor(package, router_module_pattern="routes.py")
    assert set(extractor.scan_router_modules()) == {f"{package}.users.routes"}
