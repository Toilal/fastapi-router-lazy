"""Route-infos extractors.

These extractors need nothing but FastAPI: they read a module's routes off
plain ``fastapi.APIRouter`` objects (:mod:`~fastapi_router_lazy.extractors.plain`),
from a persisted cache (:mod:`~fastapi_router_lazy.extractors.cached_extractor`),
or from a sandbox subprocess (:mod:`~fastapi_router_lazy.extractors.sandbox`).
"""

from fastapi_router_lazy.extractors.abc import (
    AbstractRouteInfosExtractor,
    CachedExtractedRouteInfos,
    ExtractorDefaults,
    ExtractorDefaultsProtocol,
    InitializableExtractor,
    RouteSources,
)
from fastapi_router_lazy.extractors.cached_extractor import (
    CachedRouteInfosExtractor,
    RouteInfosCacheMismatch,
    module_checksum,
    verify_route_infos_cache,
)
from fastapi_router_lazy.extractors.plain import (
    PlainRouteInfosExtractor,
    extract_routes_from_module,
)
from fastapi_router_lazy.extractors.sandbox import (
    SandboxRouteInfosExtractor,
    extract_routes_sandboxed,
)

__all__ = [
    "AbstractRouteInfosExtractor",
    "CachedExtractedRouteInfos",
    "CachedRouteInfosExtractor",
    "ExtractorDefaults",
    "ExtractorDefaultsProtocol",
    "InitializableExtractor",
    "PlainRouteInfosExtractor",
    "RouteInfosCacheMismatch",
    "RouteSources",
    "SandboxRouteInfosExtractor",
    "extract_routes_from_module",
    "extract_routes_sandboxed",
    "module_checksum",
    "verify_route_infos_cache",
]
