import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from conftest import MakePackage

from fastapi_router_lazy import (
    CachedExtractedRouteInfos,
    CachedRouteInfosExtractor,
    ExtractedRouteInfo,
    ExtractorDefaults,
    PlainRouteInfosExtractor,
    module_checksum,
)
from fastapi_router_lazy.extractors.abc import AbstractRouteInfosExtractor

REAL_MODULE = "fastapi_router_lazy.route_info"
OTHER_MODULE = "fastapi_router_lazy.router_loader"

USERS_ROUTER = """
from fastapi import APIRouter

router = APIRouter()


@router.get("/users")
def list_users() -> list[str]:
    return ["alice"]
"""


class TestModuleChecksum:
    def test_returns_hex_digest(self) -> None:
        result = module_checksum(REAL_MODULE)
        assert isinstance(result, str)
        assert len(result) == 64

    def test_same_module_same_checksum(self) -> None:
        assert module_checksum(REAL_MODULE) == module_checksum(REAL_MODULE)

    def test_different_modules_differ(self) -> None:
        assert module_checksum(REAL_MODULE) != module_checksum(OTHER_MODULE)

    def test_raises_for_missing_module(self) -> None:
        with pytest.raises((ValueError, ModuleNotFoundError)):
            module_checksum("nonexistent.module")


class TestWriteReadCacheFile:
    def test_roundtrip(self, tmp_path: Path) -> None:
        route_info = ExtractedRouteInfo(
            path="/items",
            router_variable="router",
            router_module="app.items.router",
            deployment="api",
        )
        data = CachedExtractedRouteInfos(
            router_checksums={"app.items.router": "abc123"},
            routes={"app.items.router": [route_info]},
        )
        cache_file = tmp_path / "routes.json"

        CachedRouteInfosExtractor._cache_file_cache.clear()
        CachedRouteInfosExtractor.write_cache_file(data, cache_file)
        CachedRouteInfosExtractor._cache_file_cache.clear()

        result = CachedRouteInfosExtractor.read_cache_file(cache_file)

        assert result.routes["app.items.router"][0].path == "/items"
        assert result.router_checksums["app.items.router"] == "abc123"

    def test_roundtrip_preserves_methods_tuple(self, tmp_path: Path) -> None:
        route_info = ExtractedRouteInfo(
            path="/items",
            methods=("GET", "POST"),
            router_variable="router",
            router_module="app.items.router",
        )
        data = CachedExtractedRouteInfos(
            router_checksums={},
            routes={"app.items.router": [route_info]},
        )
        cache_file = tmp_path / "routes.json"

        CachedRouteInfosExtractor._cache_file_cache.clear()
        CachedRouteInfosExtractor.write_cache_file(data, cache_file)
        CachedRouteInfosExtractor._cache_file_cache.clear()
        back = CachedRouteInfosExtractor.read_cache_file(cache_file).routes[
            "app.items.router"
        ][0]

        assert isinstance(back.methods, tuple)
        assert hash(back) == hash(route_info)
        assert back == route_info

    def test_roundtrip_preserves_methods_none(self, tmp_path: Path) -> None:
        route_info = ExtractedRouteInfo(
            path="/items",
            methods=None,
            router_variable="router",
            router_module="app.items.router",
        )
        data = CachedExtractedRouteInfos(
            router_checksums={},
            routes={"app.items.router": [route_info]},
        )
        cache_file = tmp_path / "routes.json"

        CachedRouteInfosExtractor._cache_file_cache.clear()
        CachedRouteInfosExtractor.write_cache_file(data, cache_file)
        CachedRouteInfosExtractor._cache_file_cache.clear()
        back = CachedRouteInfosExtractor.read_cache_file(cache_file).routes[
            "app.items.router"
        ][0]

        assert back.methods is None
        assert back == route_info

    def test_read_missing_returns_empty(self, tmp_path: Path) -> None:
        CachedRouteInfosExtractor._cache_file_cache.clear()
        result = CachedRouteInfosExtractor.read_cache_file(tmp_path / "missing.json")
        assert result.routes == {}
        assert result.router_checksums == {}

    def test_write_produces_valid_json(self, tmp_path: Path) -> None:
        data = CachedExtractedRouteInfos(
            router_checksums={"mod.router": "checksum"},
            routes={
                "mod.router": [
                    ExtractedRouteInfo(
                        path="/x", router_variable="router", router_module="mod.router"
                    )
                ]
            },
        )
        cache_file = tmp_path / "routes.json"
        CachedRouteInfosExtractor._cache_file_cache.clear()
        CachedRouteInfosExtractor.write_cache_file(data, cache_file)

        parsed = json.loads(cache_file.read_text())
        assert "router_checksums" in parsed
        assert "routes" in parsed


class TestGetInvalidModules:
    @pytest.fixture
    def mock_defaults(self) -> MagicMock:
        return MagicMock(spec=["deployment"])

    def _cached(self, data: CachedExtractedRouteInfos) -> CachedRouteInfosExtractor:
        cached = CachedRouteInfosExtractor.__new__(CachedRouteInfosExtractor)
        cached.package_name = "fastapi_router_lazy"
        cached.data = data
        return cached

    def test_no_changes_returns_empty(self) -> None:
        data = CachedExtractedRouteInfos(
            router_checksums={REAL_MODULE: module_checksum(REAL_MODULE)},
            routes={REAL_MODULE: []},
        )
        with patch.object(
            AbstractRouteInfosExtractor,
            "scan_router_modules",
            return_value=iter([REAL_MODULE]),
        ):
            assert self._cached(data).get_invalid_modules() == set()

    def test_modified_module_detected(self) -> None:
        data = CachedExtractedRouteInfos(
            router_checksums={REAL_MODULE: "stale"}, routes={REAL_MODULE: []}
        )
        with patch.object(
            AbstractRouteInfosExtractor,
            "scan_router_modules",
            return_value=iter([REAL_MODULE]),
        ):
            assert REAL_MODULE in self._cached(data).get_invalid_modules()

    def test_new_module_detected(self) -> None:
        data = CachedExtractedRouteInfos(
            router_checksums={REAL_MODULE: module_checksum(REAL_MODULE)},
            routes={REAL_MODULE: []},
        )
        with patch.object(
            AbstractRouteInfosExtractor,
            "scan_router_modules",
            return_value=iter([REAL_MODULE, OTHER_MODULE]),
        ):
            result = self._cached(data).get_invalid_modules()
        assert result == {OTHER_MODULE}

    def test_disappeared_module_detected(self) -> None:
        gone = "fastapi_router_lazy.gone"
        data = CachedExtractedRouteInfos(
            router_checksums={
                REAL_MODULE: module_checksum(REAL_MODULE),
                gone: "old",
            },
            routes={REAL_MODULE: [], gone: []},
        )
        with patch.object(
            AbstractRouteInfosExtractor,
            "scan_router_modules",
            return_value=iter([REAL_MODULE]),
        ):
            result = self._cached(data).get_invalid_modules()
        assert result == {gone}


class TestCachedExtractorInit:
    @patch.object(CachedRouteInfosExtractor, "get_invalid_modules")
    @patch.object(CachedRouteInfosExtractor, "read_cache_file")
    def test_uses_cache_when_valid(
        self, mock_read: MagicMock, mock_invalid: MagicMock
    ) -> None:
        cached_data = CachedExtractedRouteInfos(
            router_checksums={"mod.router": "abc"}, routes={"mod.router": []}
        )
        mock_read.return_value = cached_data
        mock_invalid.return_value = set()
        inner = MagicMock(spec=AbstractRouteInfosExtractor)
        inner.router_module_pattern = "router.py"

        cached = CachedRouteInfosExtractor(
            MagicMock(), "pkg", Path("/fake/routes.json"), inner
        )

        assert cached.data is cached_data
        inner.preload_from_cache.assert_called_once_with(cached_data)

    @patch.object(CachedRouteInfosExtractor, "write_cache_file_from_extractor")
    @patch.object(CachedRouteInfosExtractor, "get_invalid_modules")
    @patch.object(CachedRouteInfosExtractor, "read_cache_file")
    def test_regenerates_when_invalid(
        self, mock_read: MagicMock, mock_invalid: MagicMock, mock_write: MagicMock
    ) -> None:
        cached_data = CachedExtractedRouteInfos(
            router_checksums={"mod.router": "stale"}, routes={"mod.router": []}
        )
        new_data = CachedExtractedRouteInfos(
            router_checksums={"mod.router": "fresh"}, routes={"mod.router": []}
        )
        mock_read.return_value = cached_data
        mock_invalid.return_value = {"mod.router"}
        mock_write.return_value = new_data
        inner = MagicMock(spec=AbstractRouteInfosExtractor)
        inner.router_module_pattern = "router.py"

        cached = CachedRouteInfosExtractor(
            MagicMock(), "pkg", Path("/fake/routes.json"), inner
        )

        mock_write.assert_called_once()
        assert cached.data is new_data

    @patch.object(CachedRouteInfosExtractor, "get_invalid_modules")
    @patch.object(CachedRouteInfosExtractor, "read_cache_file")
    def test_raises_when_invalid_and_strict(
        self, mock_read: MagicMock, mock_invalid: MagicMock
    ) -> None:
        mock_read.return_value = CachedExtractedRouteInfos({}, {})
        mock_invalid.return_value = {"mod.router"}
        inner = MagicMock(spec=AbstractRouteInfosExtractor)
        inner.router_module_pattern = "router.py"

        with pytest.raises(ValueError, match="Invalid modules detected"):
            CachedRouteInfosExtractor(
                MagicMock(), "pkg", Path("/fake/routes.json"), inner, strict=True
            )


class TestCachedExtractorIntegration:
    def test_write_and_read_from_real_package(
        self, make_package: MakePackage, tmp_path: Path
    ) -> None:
        package = make_package({"users.router": USERS_ROUTER})
        inner = PlainRouteInfosExtractor(ExtractorDefaults(), package)
        cache_file = tmp_path / "routes.json"
        CachedRouteInfosExtractor._cache_file_cache.clear()

        data = CachedRouteInfosExtractor.write_cache_file_from_extractor(
            inner, cache_file
        )

        assert len(data.routes) == 1
        for module_name, checksum in data.router_checksums.items():
            assert checksum == module_checksum(module_name)

        CachedRouteInfosExtractor._cache_file_cache.clear()
        read_data = CachedRouteInfosExtractor.read_cache_file(cache_file)
        assert set(read_data.routes) == set(data.routes)

    def test_end_to_end_cache_hit(
        self, make_package: MakePackage, tmp_path: Path
    ) -> None:
        package = make_package({"users.router": USERS_ROUTER})
        cache_file = tmp_path / "routes.json"
        CachedRouteInfosExtractor._cache_file_cache.clear()

        inner = PlainRouteInfosExtractor(ExtractorDefaults(), package)
        cached = CachedRouteInfosExtractor(
            ExtractorDefaults(), package, cache_file, inner
        )

        infos = cached.extract_module_route_infos(f"{package}.users.router")
        assert [i.path for i in infos] == ["/users"]
