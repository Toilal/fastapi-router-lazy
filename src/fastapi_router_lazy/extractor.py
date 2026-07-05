"""Factory assembling a route-infos extractor from simple parameters."""

import logging
from pathlib import Path

from fastapi_router_lazy.extractors.abc import (
    DEFAULT_ROUTER_MODULE_PATTERN,
    AbstractRouteInfosExtractor,
    ExtractorDefaults,
    ExtractorDefaultsProtocol,
)
from fastapi_router_lazy.extractors.cached_extractor import (
    DEFAULT_CACHE_FILENAME,
    CachedRouteInfosExtractor,
)
from fastapi_router_lazy.extractors.plain import PlainRouteInfosExtractor

logger = logging.getLogger(__name__)


def route_infos_extractor(
    package_name: str,
    *,
    defaults: ExtractorDefaultsProtocol | None = None,
    extractor: AbstractRouteInfosExtractor | None = None,
    cache: bool = False,
    cache_file: Path | None = None,
    router_module_pattern: str = DEFAULT_ROUTER_MODULE_PATTERN,
    strict: bool = False,
) -> AbstractRouteInfosExtractor:
    """Build an extractor for ``package_name``.

    By default a :class:`PlainRouteInfosExtractor` (plain FastAPI, no extra
    dependency) is used. Pass ``extractor=`` to plug a different one. Set
    ``cache=True`` to wrap it in a checksum cache persisted to ``cache_file``
    (defaults to ``routes.json`` next to the package).
    """
    resolved_defaults: ExtractorDefaultsProtocol = defaults or ExtractorDefaults()

    base_extractor = extractor or PlainRouteInfosExtractor(
        resolved_defaults, package_name, router_module_pattern=router_module_pattern
    )

    if not cache:
        return base_extractor

    if cache_file is None:
        cache_file = Path.cwd() / DEFAULT_CACHE_FILENAME

    return CachedRouteInfosExtractor(
        base_extractor.defaults,
        package_name,
        cache_file,
        base_extractor,
        strict=strict,
    )
