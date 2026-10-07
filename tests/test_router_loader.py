from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import fastapi.routing
import pytest
from conftest import MakePackage
from fastapi import APIRouter, Depends, FastAPI, Request, Response, WebSocket
from fastapi.responses import JSONResponse, PlainTextResponse
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

    def test_http_routes_keep_application_dependency_overrides(self) -> None:
        def get_value() -> str:
            return "real"

        router = APIRouter()

        @router.get("/value")
        def read_value(value: str = Depends(get_value)) -> dict[str, str]:
            return {"value": value}

        app = FastAPI()
        RouterLoader._include_router(app, router)
        app.dependency_overrides[get_value] = lambda: "overridden"

        assert TestClient(app).get("/value").json() == {"value": "overridden"}

    def test_websocket_routes_keep_application_dependency_overrides(self) -> None:
        def get_value() -> str:
            return "real"

        router = APIRouter()

        @router.websocket("/value")
        async def read_value(
            websocket: WebSocket, value: str = Depends(get_value)
        ) -> None:
            await websocket.accept()
            await websocket.send_text(value)

        app = FastAPI()
        RouterLoader._include_router(app, router)
        app.dependency_overrides[get_value] = lambda: "overridden"

        with TestClient(app).websocket_connect("/value") as websocket:
            assert websocket.receive_text() == "overridden"

    def test_http_routes_keep_application_overrides_isolated(self) -> None:
        def get_value() -> str:
            return "real"

        router = APIRouter()

        @router.get("/value")
        def read_value(value: str = Depends(get_value)) -> str:
            return value

        first = FastAPI()
        second = FastAPI()
        first_route = RouterLoader._include_router(first, router)[0]
        second_route = RouterLoader._include_router(second, router)[0]
        first.dependency_overrides[get_value] = lambda: "first"
        second.dependency_overrides[get_value] = lambda: "second"

        assert first_route is not second_route
        assert TestClient(first).get("/value").json() == "first"
        assert TestClient(second).get("/value").json() == "second"

    def test_websocket_routes_keep_application_overrides_isolated(self) -> None:
        def get_value() -> str:
            return "real"

        router = APIRouter()

        @router.websocket("/value")
        async def read_value(
            websocket: WebSocket, value: str = Depends(get_value)
        ) -> None:
            await websocket.accept()
            await websocket.send_text(value)

        first = FastAPI()
        second = FastAPI()
        first_route = RouterLoader._include_router(first, router)[0]
        second_route = RouterLoader._include_router(second, router)[0]
        first.dependency_overrides[get_value] = lambda: "first"
        second.dependency_overrides[get_value] = lambda: "second"

        assert first_route is not second_route
        with TestClient(first).websocket_connect("/value") as websocket:
            assert websocket.receive_text() == "first"
        with TestClient(second).websocket_connect("/value") as websocket:
            assert websocket.receive_text() == "second"


requires_included_router = pytest.mark.skipif(
    not hasattr(fastapi.routing, "_IncludedRouter"),
    reason="FastAPI < 0.137 copies included routes",
)


def _has_included_router(app: FastAPI) -> bool:
    return any(type(route).__name__ == "_IncludedRouter" for route in app.routes)


class MarkedResponse(JSONResponse):
    def __init__(
        self, content: object = None, status_code: int = 200, **kwargs: Any
    ) -> None:
        super().__init__(content, status_code, **kwargs)
        self.headers["x-response-class"] = "include"


def _tracked(calls: list[str], name: str) -> Callable[[], None]:
    def dependency() -> None:
        calls.append(name)

    return dependency


def _items_router(calls: list[str]) -> APIRouter:
    child = APIRouter(dependencies=[Depends(_tracked(calls, "child"))])

    @child.get("/items/{item_id}", tags=["route"])
    def read_item(item_id: int) -> int:
        calls.append("endpoint")
        return item_id

    return child


class TestIncludeContextIsPreserved:
    """Loaded routes keep what their includes apply (#22).

    Since FastAPI 0.137 the include context (prefix, dependencies, tags, …) of
    the target app, of the loaded router and of nested includes lives on the
    ``_IncludedRouter`` wrapper, not on the child routes.
    """

    def test_application_dependencies_run_once(self) -> None:
        calls: list[str] = []
        app = FastAPI(dependencies=[Depends(_tracked(calls, "app"))])
        RouterLoader._include_router(app, _items_router(calls))

        assert TestClient(app).get("/items/1").json() == 1
        assert calls == ["app", "child", "endpoint"]

    def test_nested_include_keeps_prefix_and_dependencies(self) -> None:
        calls: list[str] = []
        module_router = APIRouter(dependencies=[Depends(_tracked(calls, "module"))])
        module_router.include_router(
            _items_router(calls),
            prefix="/sub",
            dependencies=[Depends(_tracked(calls, "include"))],
        )
        app = FastAPI(dependencies=[Depends(_tracked(calls, "app"))])
        RouterLoader._include_router(app, module_router)
        client = TestClient(app)

        assert client.get("/sub/items/1").json() == 1
        assert calls == ["app", "module", "include", "child", "endpoint"]
        assert client.get("/items/1").status_code == 404

    def test_nested_include_settings_reach_openapi_and_responses(self) -> None:
        calls: list[str] = []
        hidden = APIRouter(include_in_schema=False)

        @hidden.get("/hidden")
        def read_hidden() -> str:
            return "hidden"

        module_router = APIRouter()
        module_router.include_router(
            _items_router(calls),
            prefix="/sub",
            tags=["include"],
            responses={418: {"description": "Teapot"}},
            default_response_class=MarkedResponse,
        )
        module_router.include_router(hidden)
        app = FastAPI()
        RouterLoader._include_router(app, module_router)
        client = TestClient(app)

        paths = app.openapi()["paths"]
        assert list(paths) == ["/sub/items/{item_id}"]
        operation = paths["/sub/items/{item_id}"]["get"]
        assert operation["tags"] == ["include", "route"]
        assert "418" in operation["responses"]
        assert client.get("/sub/items/1").headers["x-response-class"] == "include"
        assert client.get("/hidden").json() == "hidden"

    def test_nested_include_dependencies_are_overridable(self) -> None:
        calls: list[str] = []
        include_dependency = _tracked(calls, "include")
        module_router = APIRouter()
        module_router.include_router(
            _items_router(calls), dependencies=[Depends(include_dependency)]
        )
        app = FastAPI()
        RouterLoader._include_router(app, module_router)
        app.dependency_overrides[include_dependency] = _tracked(calls, "override")

        assert TestClient(app).get("/items/1").json() == 1
        assert calls == ["override", "child", "endpoint"]

    @requires_included_router
    def test_nested_include_serves_websocket_route_and_mount(self) -> None:
        calls: list[str] = []
        child = APIRouter()

        @child.websocket("/ws")
        async def echo(websocket: WebSocket) -> None:
            await websocket.accept()
            await websocket.send_text("ws")

        async def plain(request: Request) -> Response:
            return PlainTextResponse("plain")

        child.add_route("/plain", plain)
        child.mount("/static", app=PlainTextResponse("mounted"))
        module_router = APIRouter()
        module_router.include_router(
            child, prefix="/sub", dependencies=[Depends(_tracked(calls, "include"))]
        )
        app = FastAPI()
        RouterLoader._include_router(app, module_router)
        client = TestClient(app)

        with client.websocket_connect("/sub/ws") as websocket:
            assert websocket.receive_text() == "ws"
        assert calls == ["include"]
        assert client.get("/sub/plain").text == "plain"
        assert client.get("/sub/static/file").text == "mounted"

    @requires_included_router
    def test_no_included_router_left_in_serving_routes(self) -> None:
        calls: list[str] = []
        module_router = APIRouter(dependencies=[Depends(_tracked(calls, "module"))])
        module_router.include_router(_items_router(calls), prefix="/sub")
        app = FastAPI()

        added = RouterLoader._include_router(app, module_router)

        assert added
        assert not _has_included_router(app)

    @pytest.mark.skipif(
        not hasattr(APIRouter, "frontend"), reason="FastAPI < 0.138 has no frontend"
    )
    def test_include_with_frontend_routes_stays_wrapped(self, tmp_path: Path) -> None:
        (tmp_path / "index.html").write_text("<p>frontend</p>")
        module_router = APIRouter()
        module_router.frontend("/web", directory=tmp_path)

        @module_router.get("/api")
        def api() -> str:
            return "api"

        app = FastAPI()
        RouterLoader._include_router(app, module_router)
        client = TestClient(app)

        assert _has_included_router(app)
        assert "frontend" in client.get("/web/").text
        assert client.get("/api").json() == "api"
