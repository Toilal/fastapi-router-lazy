"""Route-infos extractors.

The core extractors (:mod:`~fastapi_router_lazy.extractors.plain`,
:mod:`~fastapi_router_lazy.extractors.cached_extractor`,
:mod:`~fastapi_router_lazy.extractors.sandbox`) need nothing but FastAPI. The
variant-aware extractors live in
:mod:`fastapi_router_lazy.extractors.variants` and must be imported explicitly
(they require the optional ``variants`` extra).
"""

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

__all__ = [
    "AbstractRouteInfosExtractor",
    "CachedExtractedRouteInfos",
    "CachedRouteInfosExtractor",
    "ExtractorDefaults",
    "ExtractorDefaultsProtocol",
    "InitializableExtractor",
    "PlainRouteInfosExtractor",
    "SandboxRouteInfosExtractor",
    "extract_routes_from_module",
    "extract_routes_sandboxed",
    "module_checksum",
]
