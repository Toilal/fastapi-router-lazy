import sys

import pytest
from conftest import MakePackage

from fastapi_router_lazy import RouteSources
from fastapi_router_lazy.extractors.route_sources import (
    module_file,
    read_route_sources,
    router_checksum,
)

ROUTER = """
from fastapi import APIRouter

from .settings import NAMES

{declaration}

router = APIRouter()

for name in NAMES:
    router.get(f"/{{name}}")(lambda: None)
"""


def _read(make_package: MakePackage, declaration: str) -> RouteSources | None:
    package = make_package(
        {
            "app.settings": 'NAMES = ("a", "b")',
            "app.router": ROUTER.format(declaration=declaration),
        }
    )
    return read_route_sources(f"{package}.app.router")


class TestReadRouteSources:
    def test_a_router_without_declaration_has_none(
        self, make_package: MakePackage
    ) -> None:
        assert _read(make_package, "") is None

    @pytest.mark.parametrize(
        "declaration",
        [
            '__route_sources__ = ("{package}.app.settings", "json")',
            '__route_sources__: list[str] = ["json", "{package}.app.settings"]',
        ],
        ids=["tuple", "annotated-list"],
    )
    def test_a_declaration_lists_the_modules(
        self, make_package: MakePackage, declaration: str
    ) -> None:
        package = make_package({"app.settings": 'NAMES = ("a", "b")', "app.router": ""})
        router = ROUTER.format(declaration=declaration.format(package=package))
        (module_file(f"{package}.app.router") or pytest.fail("no router")).write_text(
            router
        )

        assert read_route_sources(f"{package}.app.router") == RouteSources(
            tuple(sorted((f"{package}.app.settings", "json")))
        )

    def test_an_empty_declaration_lists_nothing(
        self, make_package: MakePackage
    ) -> None:
        assert _read(make_package, "__route_sources__ = ()") == RouteSources(())

    @pytest.mark.parametrize(
        ("declaration", "error"),
        [
            (
                "__route_sources__ = tuple(['json'])",
                "__route_sources__ must be a tuple or list of module names",
            ),
            (
                '__route_sources__ = ("json", "nowhere.at_all")',
                "declared route sources not found: nowhere.at_all",
            ),
        ],
        ids=["computed", "missing-module"],
    )
    def test_an_invalid_declaration_has_an_error(
        self, make_package: MakePackage, declaration: str, error: str
    ) -> None:
        result = _read(make_package, declaration)

        assert result is not None
        assert result.error is not None
        assert error in result.error


class TestModuleFile:
    def test_finds_a_submodule_without_importing_its_package(
        self, make_package: MakePackage
    ) -> None:
        package = make_package({"deep.inner.mod": "X = 1"})

        path = module_file(f"{package}.deep.inner.mod")

        assert path is not None
        assert path.read_text() == "X = 1"
        assert package not in sys.modules

    def test_returns_none_for_a_missing_module(self) -> None:
        assert module_file("fastapi_router_lazy.nowhere") is None
        assert module_file("nowhere_at_all") is None


class TestRouterChecksum:
    def test_without_route_sources_it_is_the_router_own_checksum(self) -> None:
        assert router_checksum("m.router", (), "own") == "own"

    def test_it_follows_the_content_of_the_route_sources(
        self, make_package: MakePackage
    ) -> None:
        package = make_package({"names": 'NAME = "x"'})
        source = f"{package}.names"
        before = router_checksum("m.router", (source,), "own")

        (module_file(source) or pytest.fail("not found")).write_text('NAME = "y"')

        assert router_checksum("m.router", (source,), "own") != before
