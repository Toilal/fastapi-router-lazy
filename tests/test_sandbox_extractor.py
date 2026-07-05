import sys

import pytest
from conftest import MakePackage

import fastapi_router_lazy.extractors.sandbox as sandbox_module
from fastapi_router_lazy import (
    ExtractedRouteInfo,
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

NOISY_ROUTER = """
import sys

print("chatty import: this line goes to stdout")
sys.stdout.buffer.write(b"\\x80\\x04raw bytes that look like a pickle frame")
sys.stdout.flush()

from fastapi import APIRouter

router = APIRouter()


@router.get("/users")
def list_users() -> list[str]:
    return ["alice"]
"""

EMPTY_ROUTER = "answer = 42\n"


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


def test_sandbox_survives_module_stdout_noise(make_package: MakePackage) -> None:
    """A target module printing on import must not corrupt the pickle stream."""
    package = make_package({"noisy.router": NOISY_ROUTER})

    infos = extract_routes_sandboxed([f"{package}.noisy.router"])

    assert [i.path for i in infos] == ["/users"]


def test_sandbox_init_seeds_routeless_modules(make_package: MakePackage) -> None:
    package = make_package({"users.router": USERS_ROUTER, "empty.router": EMPTY_ROUTER})
    extractor = SandboxRouteInfosExtractor(ExtractorDefaults(), package)

    extractor.init()

    empty_module = f"{package}.empty.router"
    assert empty_module in extractor.modules
    assert extractor.modules[empty_module] == []


def test_sandbox_routeless_module_does_not_respawn(
    make_package: MakePackage, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package({"users.router": USERS_ROUTER, "empty.router": EMPTY_ROUTER})
    extractor = SandboxRouteInfosExtractor(ExtractorDefaults(), package)
    extractor.init()

    spawns: list[list[str]] = []
    original = sandbox_module.extract_routes_sandboxed

    def _counting(
        modules: list[str], python_executable: str = sys.executable
    ) -> list[ExtractedRouteInfo]:
        spawns.append(modules)
        return original(modules, python_executable)

    monkeypatch.setattr(sandbox_module, "extract_routes_sandboxed", _counting)

    assert extractor.extract_module_route_infos(f"{package}.empty.router") == []
    assert spawns == []
