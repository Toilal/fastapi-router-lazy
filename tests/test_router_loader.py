from unittest.mock import MagicMock, patch

import pytest
from conftest import MakePackage
from fastapi import APIRouter, FastAPI
from starlette.testclient import TestClient

from fastapi_router_lazy import (
    ExtractedRouteInfo,
    ExtractorDefaults,
    PlainRouteInfosExtractor,
    RouterLoader,
    RouterLoaderMeta,
)
from fastapi_router_lazy.extractors.abc import AbstractRouteInfosExtractor

USERS_ROUTER = """
from fastapi import APIRouter

router = APIRouter()


@router.get("/users")
def list_users() -> list[str]:
    return ["alice"]
"""


@pytest.fixture
def mock_extractor() -> MagicMock:
    return MagicMock(spec=AbstractRouteInfosExtractor)


class TestLoadRouterDeploymentFiltering:
    @patch("fastapi_router_lazy.router_loader.importlib.import_module")
    def test_skips_import_when_no_routes_match_deployment(
        self, mock_import: MagicMock, mock_extractor: MagicMock
    ) -> None:
        mock_extractor.extract_module_route_infos.return_value = [
            ExtractedRouteInfo(
                path="/alerts",
                router_variable="router",
                router_module="app.alerts.router",
                deployment="api",
            ),
        ]

        loader = RouterLoader(mock_extractor, deployments={"ndp"})
        result = loader.load_router("app.alerts.router")

        assert result == []
        mock_import.assert_not_called()

    @patch("fastapi_router_lazy.router_loader.importlib.import_module")
    def test_imports_module_when_routes_match_deployment(
        self, mock_import: MagicMock, mock_extractor: MagicMock
    ) -> None:
        mock_extractor.extract_module_route_infos.return_value = [
            ExtractedRouteInfo(
                path="/device",
                router_variable="router",
                router_module="app.ndp.router",
                deployment="ndp",
            ),
        ]
        mock_module = MagicMock()
        mock_module.router = APIRouter()
        mock_import.return_value = mock_module

        loader = RouterLoader(mock_extractor, deployments={"ndp"})
        result = loader.load_router("app.ndp.router")

        mock_import.assert_called_once_with("app.ndp.router")
        assert len(result) == 1

    @patch("fastapi_router_lazy.router_loader.importlib.import_module")
    def test_imports_module_when_no_deployment_filter(
        self, mock_import: MagicMock, mock_extractor: MagicMock
    ) -> None:
        mock_extractor.extract_module_route_infos.return_value = [
            ExtractedRouteInfo(
                path="/alerts",
                router_variable="router",
                router_module="app.alerts.router",
                deployment="api",
            ),
        ]
        mock_module = MagicMock()
        mock_module.router = APIRouter()
        mock_import.return_value = mock_module

        loader = RouterLoader(mock_extractor, deployments=None)
        result = loader.load_router("app.alerts.router")

        mock_import.assert_called_once()
        assert len(result) == 1

    @patch("fastapi_router_lazy.router_loader.importlib.import_module")
    def test_skips_import_when_extractor_returns_empty(
        self, mock_import: MagicMock, mock_extractor: MagicMock
    ) -> None:
        mock_extractor.extract_module_route_infos.return_value = []

        loader = RouterLoader(mock_extractor, deployments={"ndp"})
        result = loader.load_router("app.alerts.router")

        assert result == []
        mock_import.assert_not_called()

    @patch("fastapi_router_lazy.router_loader.importlib.import_module")
    def test_bypasses_deployment_filter_when_variables_explicit(
        self, mock_import: MagicMock, mock_extractor: MagicMock
    ) -> None:
        mock_module = MagicMock()
        mock_module.router = APIRouter()
        mock_import.return_value = mock_module

        loader = RouterLoader(mock_extractor, deployments={"ndp"})
        result = loader.load_router("app.alerts.router", variables="router")

        mock_import.assert_called_once_with("app.alerts.router")
        mock_extractor.extract_module_route_infos.assert_not_called()
        assert len(result) == 1

    @patch("fastapi_router_lazy.router_loader.importlib.import_module")
    def test_deployment_true_always_matches(
        self, mock_import: MagicMock, mock_extractor: MagicMock
    ) -> None:
        mock_extractor.extract_module_route_infos.return_value = [
            ExtractedRouteInfo(
                path="/health",
                router_variable="router",
                router_module="app.health.router",
                deployment=True,
            ),
        ]
        mock_module = MagicMock()
        mock_module.router = APIRouter()
        mock_import.return_value = mock_module

        loader = RouterLoader(mock_extractor, deployments={"ndp"})
        result = loader.load_router("app.health.router")

        mock_import.assert_called_once()
        assert len(result) == 1


class TestRealLoading:
    def test_load_mounts_routers_on_app(self, make_package: MakePackage) -> None:
        package = make_package({"users.router": USERS_ROUTER})
        extractor = PlainRouteInfosExtractor(ExtractorDefaults(), package)
        app = FastAPI()

        loaded = RouterLoader(extractor, app).load()

        assert len(loaded) == 1

        client = TestClient(app)
        assert client.get("/users").json() == ["alice"]

    def test_load_router_sets_loader_meta(self, make_package: MakePackage) -> None:
        package = make_package({"users.router": USERS_ROUTER})
        extractor = PlainRouteInfosExtractor(ExtractorDefaults(), package)
        app = FastAPI()

        loaded = RouterLoader(extractor, app).load_router(f"{package}.users.router")

        meta: RouterLoaderMeta = loaded[0].router._loader_meta  # type: ignore[attr-defined]
        assert meta == RouterLoaderMeta(f"{package}.users.router", "router")

    def test_load_router_decls_with_tuple(self, make_package: MakePackage) -> None:
        package = make_package({"users.router": USERS_ROUTER})
        extractor = PlainRouteInfosExtractor(ExtractorDefaults(), package)
        app = FastAPI()

        loaded = RouterLoader(extractor, app).load_router_decls(
            [(f"{package}.users.router", {"router"})]
        )

        assert len(loaded) == 1
        assert TestClient(app).get("/users").json() == ["alice"]

    def test_load_routers_multiple(self, make_package: MakePackage) -> None:
        package = make_package(
            {
                "users.router": USERS_ROUTER,
                "items.router": (
                    "from fastapi import APIRouter\n"
                    "router = APIRouter()\n"
                    "@router.get('/items')\n"
                    "def li() -> list[str]:\n"
                    "    return ['book']\n"
                ),
            }
        )
        extractor = PlainRouteInfosExtractor(ExtractorDefaults(), package)
        app = FastAPI()

        loaded = RouterLoader(extractor, app).load_routers(
            [f"{package}.users.router", f"{package}.items.router"]
        )

        assert len(loaded) == 2
        client = TestClient(app)
        assert client.get("/users").json() == ["alice"]
        assert client.get("/items").json() == ["book"]

    def test_missing_module_returns_empty(self, make_package: MakePackage) -> None:
        package = make_package({"users.router": USERS_ROUTER})
        extractor = PlainRouteInfosExtractor(ExtractorDefaults(), package)

        loaded = RouterLoader(extractor, FastAPI()).load_router(
            f"{package}.nope.router", variables="router"
        )
        assert loaded == []

    def test_raises_on_non_router_variable(self, make_package: MakePackage) -> None:
        package = make_package(
            {"bad.router": "from fastapi import APIRouter\nnot_a_router = 42\n"}
        )
        extractor = PlainRouteInfosExtractor(ExtractorDefaults(), package)

        with pytest.raises(ValueError, match="must be an instance of APIRouter"):
            RouterLoader(extractor, FastAPI()).load_router(
                f"{package}.bad.router", variables="not_a_router"
            )
