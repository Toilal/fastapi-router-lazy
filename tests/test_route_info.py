from fastapi_router_lazy import ExtractedRouteInfo, MetaRouteInfo, RouteInfo


def test_route_info_defaults() -> None:
    info = RouteInfo(path="/x")
    assert info.type == "http"
    assert info.methods is None


def test_extracted_route_info_build_variant_preserves_metadata() -> None:
    info = ExtractedRouteInfo(
        path="/v1/items",
        type="http",
        methods=("GET",),
        router_variable="router",
        router_module="app.items.router",
        version=1,
        prefix="/api",
        deployment="api",
        hidden=True,
    )

    variant = info.build_variant("/v2/items")

    assert variant.path == "/v2/items"
    assert variant.methods == ("GET",)
    assert variant.router_variable == "router"
    assert variant.router_module == "app.items.router"
    assert variant.version == 1
    assert variant.prefix == "/api"
    assert variant.deployment == "api"
    assert variant.hidden is True


def test_meta_route_info() -> None:
    info = MetaRouteInfo(
        path="/groups/{group_id}/config",
        methods=("GET",),
        version=3,
        router_variable="router",
    )
    assert info.path == "/groups/{group_id}/config"
    assert info.methods == ("GET",)
    assert info.version == 3
    assert info.deployment is None
