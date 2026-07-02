"""Lazy, on-demand loading of FastAPI routers.

Mount routers only when a request first matches one of their routes, keeping
application startup fast. The core works with plain ``fastapi.APIRouter``
objects and depends on nothing but FastAPI. Install the optional ``variants``
extra (``pip install fastapi-router-lazy[variants]``) to unlock the
variant/version-aware extractors built on ``fastapi-router-variants``.
"""

from fastapi_router_lazy.extractor import route_infos_extractor
from fastapi_router_lazy.extractors.abc import (
    AbstractRouteInfosExtractor,
    CachedExtractedRouteInfos,
    ExtractorDefaults,
    ExtractorDefaultsProtocol,
    InitializableExtractor,
)
from fastapi_router_lazy.extractors.cached_extractor import (
    CachedRouteInfosExtractor,
    module_checksum,
)
from fastapi_router_lazy.extractors.plain import (
    PlainRouteInfosExtractor,
    extract_routes_from_module,
)
from fastapi_router_lazy.extractors.sandbox import (
    SandboxRouteInfosExtractor,
    extract_routes_sandboxed,
)
from fastapi_router_lazy.middleware import (
    LAZY_LOADING_ROUTER_HEADER,
    LazyMiddleware,
)
from fastapi_router_lazy.middleware import (
    factory as lazy_middleware_factory,
)
from fastapi_router_lazy.route_info import (
    ExtractedRouteInfo,
    MetaRouteInfo,
    RouteInfo,
    RouteType,
)
from fastapi_router_lazy.router_loader import (
    LazyRouteRegistry,
    LoadedRouter,
    RouterLoader,
    RouterLoaderMeta,
)

__version__ = "0.1.0"

__all__ = [
    "LAZY_LOADING_ROUTER_HEADER",
    "AbstractRouteInfosExtractor",
    "CachedExtractedRouteInfos",
    "CachedRouteInfosExtractor",
    "ExtractedRouteInfo",
    "ExtractorDefaults",
    "ExtractorDefaultsProtocol",
    "InitializableExtractor",
    "LazyMiddleware",
    "LazyRouteRegistry",
    "LoadedRouter",
    "MetaRouteInfo",
    "PlainRouteInfosExtractor",
    "RouteInfo",
    "RouteType",
    "RouterLoader",
    "RouterLoaderMeta",
    "SandboxRouteInfosExtractor",
    "__version__",
    "extract_routes_from_module",
    "extract_routes_sandboxed",
    "lazy_middleware_factory",
    "module_checksum",
    "route_infos_extractor",
]
