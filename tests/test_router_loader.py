from unittest.mock import MagicMock, patch

import pytest
from conftest import MakePackage
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from starlette.testclient import TestClient

from fastapi_router_lazy import (
    ExtractedRouteInfo,
    ExtractorDefaults,
    PlainRouteInfosExtractor,
    RouterLoader,
    RouterLoaderMeta,
    flatten_routes,
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

    @patch("fastapi_router_lazy.router_loader.importlib.import_module")
    def test_deployment_false_is_always_excluded(
        self, mock_import: MagicMock, mock_extractor: MagicMock
    ) -> None:
        mock_extractor.defaults = ExtractorDefaults(deployment="api")
        mock_extractor.extract_module_route_infos.return_value = [
            ExtractedRouteInfo(
                path="/disabled",
                router_variable="router",
                router_module="app.disabled.router",
                deployment=False,
            ),
        ]

        loader = RouterLoader(mock_extractor, deployments={"api"})
        result = loader.load_router("app.disabled.router")

        assert result == []
        mock_import.assert_not_called()

    @pytest.mark.parametrize(
        ("deployment", "expected"),
        [
            (False, False),
            (True, True),
            (None, True),
            ("api", True),
            ("other", False),
        ],
    )
    def test_deployment_filter_matrix(
        self,
        mock_extractor: MagicMock,
        deployment: str | bool | None,
        expected: bool,
    ) -> None:
        mock_extractor.defaults = ExtractorDefaults(deployment="api")
        info = ExtractedRouteInfo(
            path="/x",
            router_variable="router",
            router_module="app.x.router",
            deployment=deployment,
        )

        loader = RouterLoader(mock_extractor, deployments={"api"})
        result = loader.filter_with_deployments([info])

        assert (result == [info]) is expected


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

    def test_missing_variable_warns_and_skips(
        self, make_package: MakePackage, caplog: pytest.LogCaptureFixture
    ) -> None:
        package = make_package({"users.router": USERS_ROUTER})
        extractor = PlainRouteInfosExtractor(ExtractorDefaults(), package)

        with caplog.at_level("WARNING"):
            loaded = RouterLoader(extractor, FastAPI()).load_router(
                f"{package}.users.router", variables="absent_router"
            )

        assert loaded == []
        assert "absent_router" in caplog.text
        assert f"{package}.users.router" in caplog.text

    def test_raises_on_non_router_variable(self, make_package: MakePackage) -> None:
        package = make_package(
            {"bad.router": "from fastapi import APIRouter\nnot_a_router = 42\n"}
        )
        extractor = PlainRouteInfosExtractor(ExtractorDefaults(), package)

        with pytest.raises(ValueError, match="must be an instance of APIRouter"):
            RouterLoader(extractor, FastAPI()).load_router(
                f"{package}.bad.router", variables="not_a_router"
            )


MULTI_ROUTER = """
from fastapi import APIRouter

router = APIRouter()


@router.get("/a")
def a() -> str:
    return "a"


@router.get("/b")
def b() -> str:
    return "b"
"""


class TestServingRoutesAreFlattened:
    """Regression for the FastAPI 0.139 ``_IncludedRouter`` memory bomb (#17).

    Since 0.139 ``include_router`` appends a single opaque wrapper whose
    ``.matches()`` materialises and retains the child dependency tree on first
    request. The loader must leave only real, regex-matchable routes in the
    serving table.
    """

    def test_serving_app_holds_real_routes_not_wrappers(
        self, make_package: MakePackage
    ) -> None:
        package = make_package({"multi.router": MULTI_ROUTER})
        extractor = PlainRouteInfosExtractor(ExtractorDefaults(), package)
        app = FastAPI()

        before = len(app.routes)
        RouterLoader(extractor, app).load()
        added = app.routes[before:]

        assert len(added) == 2
        assert all(isinstance(route, APIRoute) for route in added)

        client = TestClient(app)
        assert client.get("/a").json() == "a"
        assert client.get("/b").json() == "b"

    def test_flatten_routes_is_noop_on_plain_routes(self) -> None:
        app = FastAPI()

        @app.get("/x")
        def x() -> str:
            return "x"

        plain = list(app.routes)

        assert flatten_routes(plain) == plain
